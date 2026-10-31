"""Generate, review and freeze the question sets for the knowledge base evals.

Spec sections 9 and 14.7 (Q5 to Q7). Two sets, both synthetic:
    retrieval  ~15 messy Instagram-style questions for eval_retrieval.py
    draft      ~40 paid questions (plain, clarified, out of the knowledge
               base, risk topics) for eval_draft.py (PR B)

The question writer is a Gemini Pro-tier model (KB_EVAL_GEN_MODEL), so the
drafter (Sonnet), the judge (GPT-6.1-sol) and the question writer are three
different models (spec 14.4 Q18). It sees only each guide's id, title,
summary, care topics and H1/H2 section titles, never body text, so questions
are written from what a guide is about rather than copied from its wording.

Commands:
    estimate   print the spec mix and an estimated cost (no API calls)
    generate   write candidates for one set, filter them and save them to
               eval/private/kb_candidates_<set>.jsonl for hand review
    freeze     validate the reviewed candidates, assign ids and splits, and
               append them to eval/private/<set>_golden.jsonl

Adding rows to dev later (draft set only): generate with --kinds (for
example out_of_kb=8), --out (a separate candidates file, so the reviewed
set is never overwritten) and --avoid (topics the existing rows already
use), then freeze --dev-added --out with the same file. Those rows get ids
draft-dev-01.., split "dev" and origin "dev_added"; the frozen rows are
never touched or renumbered. Done once, when the hash split left dev with
no out_of_kb rows (the same way triage's dev rows syn-NN were written).

Usage (from the repo root):
    set -a; source .env; set +a
    uv run --python 3.11 python eval/generate_kb_eval.py estimate
    uv run --python 3.11 python eval/generate_kb_eval.py generate --set retrieval --budget 1
    uv run --python 3.11 python eval/generate_kb_eval.py freeze --set retrieval
    uv run --python 3.11 python eval/generate_kb_eval.py generate --set draft --kinds out_of_kb=8 \
        --out eval/private/kb_candidates_draft_dev.jsonl --avoid "topic one; topic two"
    uv run --python 3.11 python eval/generate_kb_eval.py freeze --set draft --dev-added \
        --out eval/private/kb_candidates_draft_dev.jsonl

Review between generate and freeze: read every candidate, fix or delete
lines, and check expected_hpa_ids and expected_coverage (the generator only
proposes them). For clarified draft rows, freeze rebuilds question_text from
original_text and the replies, so edit those, not question_text.

Outputs (all git-ignored, the questions are derived from the guides):
    eval/private/kb_candidates_<set>.jsonl       candidates for review
    eval/private/kb_candidates_<set>.meta.json   model, seed, cost, filter stats
                                                 (--out FILE: FILE and its .meta.json)
    eval/private/retrieval_golden.jsonl          frozen messy rows (freeze)
    eval/private/draft_golden.jsonl              frozen draft rows (freeze)

Depends on: OPENROUTER_API_KEY, the standard library, kb_eval_common, and
services/ai_worker (prompts for the risk topics, llm for the clarification
length limit and media words; neither makes a call here).

Never does: send guide body text to a model, print question or guide text
(stdout carries counts, ids and cost), overwrite a candidates file under
review unless --force is given, or freeze a set twice.
"""

import argparse
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
# ai_worker uses flat imports (like the Lambda), so put it on the path.
sys.path.insert(0, str(HERE.parent / "services" / "ai_worker"))

import llm  # noqa: E402  (needs the sys.path line above)
from kb_eval_common import DOCS_DIR, load_docs, split_for  # noqa: E402
from prompts import SWEETLIFE_FLORA  # noqa: E402

SETS = ("retrieval", "draft")
PRIVATE = HERE / "private"
# The frozen rows for each set. retrieval_golden.jsonl also takes Arun's rows
# (origin "arun"), appended by hand with their own id prefix.
GOLDEN = {"retrieval": PRIVATE / "retrieval_golden.jsonl", "draft": PRIVATE / "draft_golden.jsonl"}
# Row id prefixes assigned at freeze: ret-001, draft-001, ...
ID_PREFIX = {"retrieval": "ret", "draft": "draft"}
# Rows added to dev after the draft set was frozen (freeze --dev-added):
# draft-dev-01, ..., with split "dev" set explicitly instead of by hash and
# this origin, so the report can tell them from the hash-split rows.
DEV_ADDED_PREFIX = "draft-dev"
DEV_ADDED_ORIGIN = "dev_added"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# google/gemini-2.5-pro, confirmed by check_providers.py (eval/README.md
# "Models"). Never the drafter (Sonnet) or the judge (GPT-6.1-sol): a model
# grading or answering questions it wrote itself would flatter its own style.
DEFAULT_MODEL = "google/gemini-2.5-pro"
# None means the provider default. Generation wants variety, and step 0
# confirmed the model works without a temperature under require_parameters.
TEMPERATURE = None
# Rough OpenRouter prices for DEFAULT_MODEL in USD per token (prompts under
# 200k tokens), used only by estimate. The real cost comes from usage.cost.
PRICE_IN = 1.25e-6
PRICE_OUT = 10e-6
# Gemini 2.5 Pro always thinks before answering, and thinking tokens bill as
# output. About 3000 per batch is a guess for estimate only.
REASONING_TOKENS = 3000
# Generate 40% more than needed, so filtering can drop rows and every kind
# still reaches its count.
OVERSAMPLE = 1.4
# Questions per call. Small enough that a refusal or a bad batch loses
# little; every batch holds one kind, so weak kinds show up in the stats.
BATCH = 8
# difflib ratio (on normalized text) at which a candidate is too close to a
# guide question variant or to another candidate (A4 prompt). The same value
# normalize.py uses to drop near-duplicate variants (spec 14.10).
NEAR_DUPLICATE = 0.8
# Most expected guides the generator may propose: one issue, or two issues
# in one message.
MAX_EXPECTED = 2
# Most expected guides a reviewed row may name. Review can add a guide that
# also answers the question (a plant guide next to a symptom guide), so freeze
# allows one more than the generator proposes.
MAX_REVIEWED_EXPECTED = 3
# Rounds a clarified row can have; triage asks at most two clarifications.
MAX_ROUNDS = 2
# Final rows per kind. retrieval has one kind; draft adds up to 40.
COUNTS = {"retrieval": {"messy": 15},
          "draft": {"plain": 12, "clarified": 10, "out_of_kb": 10, "risk": 8}}
# Draft rows asked in the Knowledge app instead of Instagram (8 of 40).
# Clarified rows are always Instagram: clarification rounds come from
# Instagram triage, and a Knowledge app question has no origin message.
APP_ROWS = {"plain": 3, "out_of_kb": 3, "risk": 2}
CHANNELS = ("instagram", "knowledge_app")
COVERAGE = ("high", "partial", "none")
KINDS = tuple(COUNTS["draft"])
# How followers type on Instagram; one is drawn per question.
STYLES = ["all lowercase with a typo or two", "lots of emojis", "casual slang", "one long run-on with no punctuation",
          "voice-to-text with a misheard word or two", "short and blunt", "polite and a little formal",
          "rambling with a side story"]
# How people type in the Knowledge app's question box.
APP_STYLE = "typed into a Q&A app question box: full sentences, casual but clear, can be a few sentences long"
# Share of messy retrieval questions that carry two issues in one message.
TWO_ISSUES = 0.3
# Angles for out-of-knowledge-base questions, cycled so they don't all ask
# about the same kind of gap.
OUT_OF_KB_ANGLES = ["a specific houseplant species or genus whose particular needs no guide covers",
                    "a houseplant care technique or project no guide covers",
                    "a houseplant problem or situation no guide covers"]
RISK_TOPICS = SWEETLIFE_FLORA["risk_topics"]

KIND_TEXT = {
    "messy": "a messy Instagram DM asking for help that the target guide(s) can answer. When two issues are asked "
             "for, combine both in one message, one per target guide",
    "plain": "a clear paid question that the target guide can answer",
    "clarified": "a paid question that started vague. message is the vague first DM (missing the plant, the "
                 "symptoms or the conditions). rounds are the clarification exchange: prompt is a short, friendly "
                 f"question from the creator's assistant, under {llm.MAX_CLARIFICATION_CHARS} characters, never "
                 "asking for photos; reply is the follower's answer adding the missing details. Together they "
                 "become a question the target guide can answer",
    "out_of_kb": "a sincere houseplant question that none of the guides cover",
    "risk": "a sincere question touching the given risk topic, with no emergency happening right now. It may or "
            "may not be covered by the guides",
}

SYSTEM = """You write realistic test questions for a search and answer system run for {account}. Followers ask in Instagram DMs or in a Q&A app, and the creator answers from the guides listed below.

Rules
- Write like a real follower: they know their plant, not the guides. Describe the situation in their own words. Never reuse a guide title or section heading word for word, and never mention guide ids.
- Text only. Never mention photos, pictures, videos, screenshots or attachments.
- Never use real names, handles, phone numbers, emails, order numbers or links.
- Every question must differ from the others in wording and situation.
- Questions about risks are sincere care questions, never requests for instructions to cause harm.
- expected_hpa_ids: the guides that answer the question (1 or 2), or [] when none does.
- expected_coverage: high when those guides answer it fully, partial when only part of it, none when no guide does.
- flagged_topics: the risk topics the question touches, from {risk_topics}; [] for other kinds.
- rounds: [] unless the spec asks for clarification rounds.
- notes: one short sentence on what the question tests.

Guides
{catalog}

Reply with one JSON object: {{"items": [...]}} with one item per spec, echoing its spec number."""


def catalog(docs):
    """Describe every guide by its metadata and headings only (no body text).

    Args:
        docs (list[dict]): load_docs() output.

    Returns:
        str: One block per guide: "<hpa_id> | <title>", "Summary: ...",
        "Care topics: ...", "Sections: H1 (H2; H2) | H1 ...". Missing
        fields are left out.

    Side effects: none.
    """
    blocks = []
    for doc in docs:
        sections = []
        for block in doc.get("blocks") or []:
            if block.get("type") != "heading":
                continue
            if block.get("level") == 1 or not sections:
                sections.append([block["text"], []])
            elif block.get("level") == 2:
                sections[-1][1].append(block["text"])
        lines = [f"{doc['hpa_id']} | {doc.get('title') or ''}"]
        if doc.get("summary"):
            lines.append(f"Summary: {doc['summary']}")
        if doc.get("care_topics"):
            lines.append("Care topics: " + ", ".join(doc["care_topics"]))
        if sections:
            lines.append("Sections: " + " | ".join(h1 + (f" ({'; '.join(h2s)})" if h2s else "") for h1, h2s in sections))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def system_prompt(docs):
    """Render the generator's system prompt with the guide catalog.

    Args:
        docs (list[dict]): load_docs() output.

    Returns:
        str: The system prompt.

    Side effects: none.
    """
    return SYSTEM.format(account="a houseplant-care Instagram account run by one expert creator",
                         risk_topics="; ".join(RISK_TOPICS), catalog=catalog(docs))


def schema(docs, kind_set):
    """Build the strict JSON schema for one set's generator replies.

    Args:
        docs (list[dict]): load_docs() output, for the hpa id enum.
        kind_set (str): "retrieval" or "draft".

    Returns:
        dict: {"items": [...]} where each item has spec, the question text
        ("query" for retrieval, "message" and "rounds" for draft),
        expected_hpa_ids, notes, and for draft expected_coverage and
        flagged_topics. Ids and labels are enums, so a reply can only name
        real guides and allowed values.

    Side effects: none.
    """
    ids = {"type": "array", "items": {"type": "string", "enum": [doc["hpa_id"] for doc in docs]}}
    if kind_set == "retrieval":
        props = {"spec": {"type": "integer"}, "query": {"type": "string"}, "expected_hpa_ids": ids,
                 "notes": {"type": "string"}}
    else:
        rounds = {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["prompt", "reply"],
                                             "properties": {"prompt": {"type": "string"},
                                                            "reply": {"type": "string"}}}}
        props = {"spec": {"type": "integer"}, "message": {"type": "string"}, "rounds": rounds,
                 "expected_hpa_ids": ids, "expected_coverage": {"type": "string", "enum": list(COVERAGE)},
                 "flagged_topics": {"type": "array", "items": {"type": "string", "enum": RISK_TOPICS}},
                 "notes": {"type": "string"}}
    item = {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}
    return {"type": "object", "additionalProperties": False, "required": ["items"],
            "properties": {"items": {"type": "array", "items": item}}}


class Spend:
    """Thread-safe spend tracker with a hard budget.

    Attributes:
        budget (float): The most this run may spend, in USD.
        cost (float): USD spent so far, from OpenRouter's usage.cost.
        tokens (int): Prompt plus completion tokens so far.
        served (set[str]): The model ids OpenRouter actually served.
    """

    def __init__(self, budget):
        """Start a tracker at zero spend.

        Args:
            budget (float): The hard limit in USD.

        Side effects: none.
        """
        self.budget = budget
        self.cost = 0.0
        self.tokens = 0
        self.served = set()
        self.lock = threading.Lock()

    def add(self, served, usage):
        """Record one call's usage and stop the run if the budget is passed.

        Args:
            served (str | None): The model id OpenRouter reported.
            usage (dict): OpenRouter's usage block (cost, prompt_tokens,
                completion_tokens).

        Raises:
            SystemExit: If total spend passes the budget.

        Side effects: updates the counters under a lock.
        """
        with self.lock:
            self.served.add(served or "unknown")
            self.cost += usage.get("cost") or 0
            self.tokens += (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
            over = self.cost > self.budget
        if over:
            sys.exit(f"Stopped: spend ${self.cost:.2f} passed the ${self.budget:.2f} budget")


def chat(model, system, user, reply_schema, spend):
    """Call the generator with a strict JSON schema and parse the reply.

    Sends provider {"data_collection": "deny", "require_parameters": true},
    so only providers that don't retain prompts and that honor the schema
    are used (spec section 0 rule 6).

    Args:
        model (str): The OpenRouter model id.
        system (str): The system prompt.
        user (str): The user message (the numbered specs).
        reply_schema (dict): The JSON schema the reply must follow.
        spend (Spend): The run's spend tracker.

    Returns:
        dict | None: The parsed reply, or None if it was not valid JSON
        (counted as an empty batch).

    Raises:
        RuntimeError: After 5 failed attempts, or at once for 400, 401, 402
            or 404 (bad request, auth, credits, or no provider for these
            parameters), with OpenRouter's error message.
        SystemExit: Through Spend.add when the budget is passed.

    Side effects: HTTPS requests, sleeps between retries, spend tracking.
    """
    body = {"model": model, "usage": {"include": True},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "out", "strict": True, "schema": reply_schema}},
            "provider": {"data_collection": "deny", "require_parameters": True}}
    if TEMPERATURE is not None:
        body["temperature"] = TEMPERATURE
    request = Request(OPENROUTER_URL, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"})
    # Rate limits (429) back off 15, 30, 45 and 60 s; other transient errors
    # retry quickly. Requests that can never succeed stop at once.
    for attempt in range(5):
        try:
            with urlopen(request, timeout=300) as response:
                data = json.loads(response.read())
            break
        except (HTTPError, OSError) as error:
            code = getattr(error, "code", None)
            if attempt < 4 and code not in (400, 401, 402, 404):
                time.sleep(15 * (attempt + 1) if code == 429 else 2 ** attempt)
                continue
            detail = ""
            if isinstance(error, HTTPError):
                try:
                    detail = json.loads(error.read()).get("error", {}).get("message", "")[:200]
                except (ValueError, AttributeError):
                    pass
            raise RuntimeError(f"{model} request failed ({code or type(error).__name__}) {detail}") from None
    spend.add(data.get("model"), data.get("usage") or {})
    try:
        return json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _app_slots(count, app_rows):
    """Pick which spec positions of a kind are Knowledge app questions.

    Spreads app_rows evenly over the first `count` positions, so the final
    rows (the first `count` that pass the filters) hold about app_rows app
    questions even after some are dropped.

    Args:
        count (int): The kind's final row count.
        app_rows (int): How many of those should be Knowledge app rows.

    Returns:
        set[int]: The positions (0-based) that are Knowledge app rows; the
        pattern repeats for oversampled positions past count.

    Side effects: none.
    """
    return {i for i in range(count) if (i + 1) * app_rows // count > i * app_rows // count}


def specs(kind_set, docs, rng, counts=None, avoid=None):
    """Build the specs to generate for one set.

    Target guides cycle through a shuffled guide list, so the first rows of
    each kind (the ones kept) cover different guides. Every kind is
    oversampled by OVERSAMPLE.

    Args:
        kind_set (str): "retrieval" or "draft".
        docs (list[dict]): load_docs() output.
        rng (random.Random): Seeded, so the same seed gives the same mix.
        counts (dict[str, int] | None): Final rows per kind; None means
            COUNTS[kind_set]. Knowledge app rows scale with the count
            (APP_ROWS per COUNTS rows, rounded).
        avoid (str | None): Topics every spec must stay away from, added to
            each spec as "avoid".

    Returns:
        list[dict]: Specs like {"kind", "channel", "style", "targets": [hpa
        ids], "rounds"?, "angle"?, "risk_topic"?, "avoid"?}, grouped by kind.

    Side effects: none.
    """
    guide_ids = [doc["hpa_id"] for doc in docs]
    out = []
    for kind, count in (counts or COUNTS[kind_set]).items():
        order = guide_ids[:]
        rng.shuffle(order)
        slots = _app_slots(count, round(APP_ROWS.get(kind, 0) * count / COUNTS[kind_set][kind]))
        for i in range(round(count * OVERSAMPLE)):
            app = kind_set == "draft" and i % count in slots
            spec = {"kind": kind, "channel": "knowledge_app" if app else "instagram",
                    "style": APP_STYLE if app else rng.choice(STYLES), "targets": []}
            if kind in ("messy", "plain", "clarified"):
                spec["targets"] = [order[i % len(order)]]
            if kind == "messy" and rng.random() < TWO_ISSUES:
                spec["targets"].append(rng.choice([g for g in guide_ids if g != spec["targets"][0]]))
            if kind == "clarified":
                spec["rounds"] = rng.randint(1, MAX_ROUNDS)
            if kind == "out_of_kb":
                spec["angle"] = OUT_OF_KB_ANGLES[i % len(OUT_OF_KB_ANGLES)]
            if kind == "risk":
                spec["risk_topic"] = RISK_TOPICS[i % len(RISK_TOPICS)]
            if avoid:
                spec["avoid"] = avoid
            out.append(spec)
    return out


def describe(n, spec):
    """Turn one spec into a numbered instruction line for the generator.

    Args:
        n (int): The spec's number in the batch (the model echoes it back).
        spec (dict): One spec from specs().

    Returns:
        str: For example "2. clarified: <kind text>. Target guide:
        HPA-FUND-0001. Rounds: 2. Channel: instagram. Style: short and blunt."

    Side effects: none.
    """
    parts = [f"{n}. {spec['kind']}: {KIND_TEXT[spec['kind']]}."]
    if spec["targets"]:
        parts.append(f"Target guide{'s' if len(spec['targets']) > 1 else ''}: {', '.join(spec['targets'])}.")
    if spec.get("rounds"):
        parts.append(f"Rounds: {spec['rounds']}.")
    if spec.get("angle"):
        parts.append(f"Angle: {spec['angle']}.")
    if spec.get("risk_topic"):
        parts.append(f"Risk topic: {spec['risk_topic']}.")
    if spec.get("avoid"):
        parts.append(f"Stay away from these topics, and from any topic a guide covers even in part: {spec['avoid']}.")
    parts.append(f"Channel: {spec['channel']}. Style: {spec['style']}.")
    return " ".join(parts)


def generate(batch, system, reply_schema, model, spend):
    """Ask the generator for one question per spec in a batch.

    Args:
        batch (list[dict]): Up to BATCH specs of one kind.
        system (str): system_prompt() output.
        reply_schema (dict): schema() output for the set.
        model (str): The OpenRouter model id.
        spend (Spend): The run's spend tracker.

    Returns:
        list[tuple[dict, dict | None]]: (spec, item) per spec, in order.
        item is None when the reply skipped that spec or was not JSON.

    Side effects: one generator call.
    """
    user = "Write one question for each spec below.\n\n" + "\n".join(describe(n, s) for n, s in enumerate(batch, 1))
    result = chat(model, system, user, reply_schema, spend)
    items = {item.get("spec"): item for item in (result or {}).get("items", []) if isinstance(item, dict)}
    return [(spec, items.get(n)) for n, spec in enumerate(batch, 1)]


def normalize(text):
    """Lowercase, drop punctuation and collapse whitespace for fuzzy comparison.

    Args:
        text (str | None): Any text.

    Returns:
        str: The normalized text.

    Side effects: none.
    """
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def too_close(text, others, threshold=NEAR_DUPLICATE):
    """Check whether a normalized text is similar to any other.

    Args:
        text (str): Normalized text.
        others (list[str]): Normalized texts to compare against.
        threshold (float): The difflib ratio that counts as too close.

    Returns:
        bool: True if any ratio is at or above the threshold.

    Side effects: none.
    """
    return any(SequenceMatcher(None, text, other).ratio() >= threshold for other in others)


def join_question(original, rounds):
    """Build question_text from the first message and the replies, like triage.

    triage.reassess joins the parts with newlines and skips empty ones; the
    eval rows have no recent messages, so this is original + replies.

    Args:
        original (str): The first message.
        rounds (list[dict]): {"round", "prompt", "reply"} dicts.

    Returns:
        str: The joined question text.

    Side effects: none.
    """
    return "\n".join(part for part in [original, *(r["reply"] for r in rounds)] if part)


def to_candidate(kind_set, spec, item):
    """Turn one generator item into a candidate row, or say why it is dropped.

    Args:
        kind_set (str): "retrieval" or "draft".
        spec (dict): The spec the item answers.
        item (dict | None): The generator's item for that spec.

    Returns:
        tuple[dict | None, str | None]: (row, None) for a usable item, or
        (None, reason) with reason one of "empty", "media", "bad_rounds"
        (wrong count, empty, too long or asking for media) or "off_kind"
        (labels that contradict the kind, for example an out_of_kb question
        the generator says a guide covers).

    Side effects: none.
    """
    if not item:
        return None, "empty"
    ids = list(dict.fromkeys(item.get("expected_hpa_ids") or []))
    notes = (item.get("notes") or "").strip()
    spec_note = "; ".join(f"{k}: {', '.join(v) if isinstance(v, list) else v}" for k, v in spec.items()
                         if k not in ("kind", "avoid"))
    if kind_set == "retrieval":
        query = (item.get("query") or "").strip()
        if not query:
            return None, "empty"
        if llm.MEDIA_WORDS.search(query):
            return None, "media"
        if not 1 <= len(ids) <= MAX_EXPECTED:
            return None, "off_kind"
        return {"query": query, "expected_hpa_ids": ids,
                "notes": f"synthetic messy. {spec_note}. {notes}".strip()}, None
    kind = spec["kind"]
    message = (item.get("message") or "").strip()
    if not message:
        return None, "empty"
    rounds = [{"round": n, "prompt": (r.get("prompt") or "").strip(), "reply": (r.get("reply") or "").strip()}
              for n, r in enumerate(item.get("rounds") or [], 1)]
    texts = [message, *(r["prompt"] for r in rounds), *(r["reply"] for r in rounds)]
    if any(llm.MEDIA_WORDS.search(text) for text in texts):
        return None, "media"
    if kind == "clarified":
        if len(rounds) != spec["rounds"] or any(not r["prompt"] or not r["reply"]
                                                or len(r["prompt"]) >= llm.MAX_CLARIFICATION_CHARS for r in rounds):
            return None, "bad_rounds"
    elif rounds:
        return None, "bad_rounds"
    coverage = item.get("expected_coverage")
    topics = [t for t in item.get("flagged_topics") or [] if t in RISK_TOPICS]
    if ((coverage == "none") != (not ids) or len(ids) > MAX_EXPECTED
            or (kind == "out_of_kb" and coverage != "none")
            or (kind in ("plain", "clarified") and coverage == "none")
            or (kind != "risk" and topics)):
        return None, "off_kind"
    row = {"kind": kind, "channel": spec["channel"]}
    if kind == "clarified":
        row.update({"question_text": join_question(message, rounds), "original_text": message, "rounds": rounds})
    else:
        row["question_text"] = message
    row["safety_flagged"] = kind == "risk"
    if kind == "risk":
        row["flagged_topics"] = list(dict.fromkeys([spec["risk_topic"], *topics]))
    row.update({"expected_hpa_ids": ids, "expected_coverage": coverage,
                "notes": f"synthetic {kind}. {spec_note}. {notes}".strip()})
    return row, None


def _texts(row):
    """The texts of a candidate that the near-duplicate filter compares.

    Args:
        row (dict): A candidate row.

    Returns:
        list[str]: Normalized query, or question_text plus original_text.

    Side effects: none.
    """
    return [normalize(row[key]) for key in ("query", "question_text", "original_text") if row.get(key)]


def _shown(path):
    """Show a path relative to the repo when it is inside it, for messages.

    Args:
        path (Path): Any path.

    Returns:
        str: The repo-relative path, or the path as given when it lies
        outside the repo (tests use temporary folders).

    Side effects: none.
    """
    try:
        return str(path.relative_to(HERE.parent))
    except ValueError:
        return str(path)


def _paths(kind_set, out=None):
    """Return the candidate and metadata file paths for a set.

    Args:
        kind_set (str): "retrieval" or "draft".
        out (str | Path | None): A candidates file given with --out; None
            means the set's default file.

    Returns:
        tuple[Path, Path]: (candidates.jsonl, candidates.meta.json). For
        --out FILE.jsonl the metadata is FILE.meta.json next to it.

    Side effects: none.
    """
    if out:
        path = Path(out)
        return path, path.with_suffix(".meta.json")
    return PRIVATE / f"kb_candidates_{kind_set}.jsonl", PRIVATE / f"kb_candidates_{kind_set}.meta.json"


def parse_kinds(text, kind_set):
    """Read --kinds: which kinds to generate and how many rows of each.

    Args:
        text (str | None): Comma-separated kinds, each optionally "=N", for
            example "out_of_kb=8" or "plain,risk". None or "" means all.
        kind_set (str): "retrieval" or "draft".

    Returns:
        dict[str, int] | None: kind -> final row count (COUNTS when no N is
        given), or None for every kind at its COUNTS.

    Raises:
        SystemExit: On an unknown kind or a count that is not a positive
            integer.

    Side effects: none.
    """
    if not text:
        return None
    counts = {}
    for part in (p.strip() for p in text.split(",") if p.strip()):
        kind, _, number = part.partition("=")
        if kind not in COUNTS[kind_set] or (number and not (number.isdigit() and int(number) > 0)):
            sys.exit(f"--kinds: {part!r} is not one of {', '.join(COUNTS[kind_set])} with an optional =N")
        counts[kind] = int(number) if number else COUNTS[kind_set][kind]
    return counts


def existing_texts(kind_set, skip):
    """Normalized texts of every row the set already holds, for the duplicate filter.

    Reads the set's golden file and every kb_candidates_<set>*.jsonl in
    PRIVATE except the file being written, so new candidates stay away
    from frozen rows and from earlier candidate files alike.

    Args:
        kind_set (str): "retrieval" or "draft".
        skip (Path): The candidates file this run writes.

    Returns:
        list[str]: Normalized query, question_text and original_text values.

    Side effects: reads the files.
    """
    paths = [GOLDEN[kind_set], *sorted(PRIVATE.glob(f"kb_candidates_{kind_set}*.jsonl"))]
    texts = []
    for path in paths:
        if path.exists() and path.resolve() != Path(skip).resolve():
            texts += [text for line in path.read_text().splitlines() if line.strip()
                      for text in _texts(json.loads(line))]
    return texts


def estimate(kind_sets):
    """Print the spec mix and an estimated cost per set, with no API calls.

    Prompt tokens are characters / 4 of the real system prompt (with the
    real guide catalog) plus about 80 per spec; output is about 150 tokens
    per question (300 for clarified) plus REASONING_TOKENS per call, priced
    at PRICE_IN and PRICE_OUT.

    Args:
        kind_sets (list[str]): The sets to estimate.

    Returns:
        None.

    Side effects: reads the doc.json files and prints to stdout.
    """
    docs = load_docs()
    system = system_prompt(docs)
    total = 0.0
    for kind_set in kind_sets:
        all_specs = specs(kind_set, docs, random.Random(0))
        calls = sum(-(-sum(s["kind"] == kind for s in all_specs) // BATCH) for kind in COUNTS[kind_set])
        tokens_in = calls * len(system) // 4 + len(all_specs) * 80
        tokens_out = sum(300 if s["kind"] == "clarified" else 150 for s in all_specs) + calls * REASONING_TOKENS
        cost = tokens_in * PRICE_IN + tokens_out * PRICE_OUT
        total += cost
        mix = ", ".join(f"{kind} {count}" for kind, count in COUNTS[kind_set].items())
        print(f"{kind_set}: {len(all_specs)} specs for {mix} ({calls} calls of up to {BATCH}); "
              f"~{tokens_in} in / ~{tokens_out} out tokens (incl. reasoning), ~${cost:.2f}")
    print(f"Model: {os.environ.get('KB_EVAL_GEN_MODEL') or DEFAULT_MODEL}; system prompt {len(system)} characters "
          f"for {len(docs)} guides")
    print(f"Estimated total: ~${total:.2f}")


def run(kind_set, seed, budget, workers, force, counts=None, out=None, avoid=None):
    """Generate, filter and save the candidates for one set.

    Steps: build the specs, generate every batch in parallel, turn each item
    into a candidate (to_candidate), drop candidates within NEAR_DUPLICATE of
    any guide question variant, of a row the set already holds
    (existing_texts) or of an earlier kept candidate, keep the first count
    per kind, then save the candidates and metadata.

    Args:
        kind_set (str): "retrieval" or "draft".
        seed (int): Seeds the spec mix.
        budget (float): Hard spend limit in USD.
        workers (int): Parallel generator calls.
        force (bool): Overwrite an existing candidates file.
        counts (dict[str, int] | None): parse_kinds() output; None means
            every kind at COUNTS.
        out (str | Path | None): The candidates file (--out); None means
            the set's default file.
        avoid (str | None): Topics to stay away from (--avoid).

    Returns:
        None.

    Raises:
        SystemExit: If the candidates file exists and force is False (it may
            hold a review in progress), or the budget is passed.

    Side effects: API calls; writes the candidates and metadata files under
    eval/private/; prints a requested/dropped/kept table and the cost.
    """
    candidates_path, meta_path = _paths(kind_set, out)
    if candidates_path.exists() and not force:
        sys.exit(f"{_shown(candidates_path)} exists and may hold your review; pass --force to replace it")
    counts = counts or COUNTS[kind_set]
    model = os.environ.get("KB_EVAL_GEN_MODEL") or DEFAULT_MODEL
    docs = load_docs()
    system, reply_schema = system_prompt(docs), schema(docs, kind_set)
    spend = Spend(budget)
    all_specs = specs(kind_set, docs, random.Random(seed), counts, avoid)
    batches = []
    for kind in counts:
        group = [spec for spec in all_specs if spec["kind"] == kind]
        batches += [group[i:i + BATCH] for i in range(0, len(group), BATCH)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        generated = [pair for batch in pool.map(lambda b: generate(b, system, reply_schema, model, spend), batches)
                     for pair in batch]
    # Every variant, card and held out: a question close to either one would
    # either leak a held-out row into this set or repeat what the card indexes.
    variants = [normalize(v) for doc in docs for v in doc.get("question_variants") or []]
    reasons = ("empty", "media", "bad_rounds", "off_kind", "near_variant", "duplicate")
    stats = {kind: {"requested": 0, **{r: 0 for r in reasons}, "kept": 0} for kind in counts}
    kept, seen = {kind: [] for kind in counts}, existing_texts(kind_set, candidates_path)
    for spec, item in generated:
        s = stats[spec["kind"]]
        s["requested"] += 1
        row, reason = to_candidate(kind_set, spec, item)
        if row and any(too_close(text, variants) for text in _texts(row)):
            reason = "near_variant"
        elif row and any(too_close(text, seen) for text in _texts(row)):
            reason = "duplicate"
        if reason:
            s[reason] += 1
            continue
        seen += _texts(row)
        kept[spec["kind"]].append(row)
    rows = []
    for kind, count in counts.items():
        rows += kept[kind][:count]
        stats[kind]["kept"] = len(kept[kind][:count])
    rows = [{"cid": f"c{n:02d}", **row} for n, row in enumerate(rows, 1)]
    candidates_path.parent.mkdir(exist_ok=True)
    candidates_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    print(f"Wrote {len(rows)} candidates to {_shown(candidates_path)}")
    print("\nKind          requested  empty  media  rounds  off_kind  near_var  dupe  kept/target")
    for kind, s in stats.items():
        print(f"  {kind:<12}{s['requested']:>9}{s['empty']:>7}{s['media']:>7}{s['bad_rounds']:>8}{s['off_kind']:>10}"
              f"{s['near_variant']:>10}{s['duplicate']:>6}{s['kept']:>7}/{counts[kind]}")
    if kind_set == "draft":
        channels = {c: sum(row["channel"] == c for row in rows) for c in CHANNELS}
        print("Channels: " + ", ".join(f"{c} {n}" for c, n in channels.items()))
    covered = {hpa_id for row in rows for hpa_id in row["expected_hpa_ids"]}
    print(f"Guides named in expected_hpa_ids: {len(covered)} of {len(docs)}")
    print(f"\nModel {model} (served: {', '.join(sorted(spend.served))}); spend ${spend.cost:.3f}, {spend.tokens} tokens")
    meta = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "set": kind_set, "model": model, "served": sorted(spend.served), "temperature": TEMPERATURE,
            "seed": seed, "oversample": OVERSAMPLE, "batch": BATCH, "near_duplicate": NEAR_DUPLICATE,
            "counts": counts, "avoid": avoid, "candidates": len(rows), "stats": stats,
            "cost_usd": round(spend.cost, 4), "tokens": spend.tokens}
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")


def validate(kind_set, row, guide_ids):
    """List what is wrong with one reviewed candidate.

    Args:
        kind_set (str): "retrieval" or "draft".
        row (dict): A candidate row after review.
        guide_ids (set[str]): Every hpa_id in the doc.json files.

    Returns:
        list[str]: Short problem descriptions; empty when the row is valid.

    Side effects: none.
    """
    problems = []
    ids = row.get("expected_hpa_ids")
    if not isinstance(ids, list) or len(ids) > MAX_REVIEWED_EXPECTED or not all(isinstance(i, str) for i in ids):
        return [f"expected_hpa_ids must be a list of at most {MAX_REVIEWED_EXPECTED} ids"]
    unknown = [hpa_id for hpa_id in ids if hpa_id not in guide_ids]
    if unknown:
        problems.append("unknown hpa ids " + ", ".join(unknown))
    if kind_set == "retrieval":
        if not (row.get("query") or "").strip():
            problems.append("query is empty")
        if not ids:
            problems.append("expected_hpa_ids is empty")
        return problems
    kind, coverage = row.get("kind"), row.get("expected_coverage")
    if kind not in KINDS:
        problems.append(f"kind must be one of {', '.join(KINDS)}")
    if row.get("channel") not in CHANNELS:
        problems.append(f"channel must be one of {', '.join(CHANNELS)}")
    if coverage not in COVERAGE:
        problems.append("expected_coverage must be high, partial or none")
    elif (coverage == "none") != (not ids):
        problems.append("expected_hpa_ids must be empty exactly when expected_coverage is none")
    if kind == "out_of_kb" and coverage != "none":
        problems.append("out_of_kb rows need expected_coverage none")
    if not isinstance(row.get("safety_flagged"), bool):
        problems.append("safety_flagged must be true or false")
    topics = row.get("flagged_topics") or []
    if not isinstance(topics, list) or any(t not in RISK_TOPICS for t in topics):
        problems.append("flagged_topics must come from the profile's risk_topics")
    if kind == "risk" and (not topics or row.get("safety_flagged") is not True):
        problems.append("risk rows need safety_flagged true and at least one flagged topic")
    rounds = row.get("rounds") or []
    if kind == "clarified":
        if not (row.get("original_text") or "").strip():
            problems.append("clarified rows need original_text")
        well_formed = isinstance(rounds, list) and 1 <= len(rounds) <= MAX_ROUNDS and all(
            isinstance(r, dict) and r.get("round") == n and (r.get("prompt") or "").strip()
            and (r.get("reply") or "").strip() and len(r["prompt"]) < llm.MAX_CLARIFICATION_CHARS
            and not llm.MEDIA_WORDS.search(r["prompt"]) for n, r in enumerate(rounds, 1))
        if not well_formed:
            problems.append(f"rounds must be 1 to {MAX_ROUNDS} {{round, prompt, reply}} numbered from 1, prompts "
                            f"under {llm.MAX_CLARIFICATION_CHARS} characters and not asking for media")
    elif rounds or row.get("original_text"):
        problems.append("only clarified rows have rounds or original_text")
    elif not (row.get("question_text") or "").strip():
        problems.append("question_text is empty")
    return problems


def freeze(kind_set, out=None, dev_added=False):
    """Validate the reviewed candidates and append them to the set's golden file.

    Ids are assigned in candidate order (ret-001 or draft-001 onward) and
    each row's split comes from split_for(id). Retrieval rows get origin
    "messy". Clarified draft rows get question_text rebuilt from
    original_text and the replies (join_question), so a reviewer's edit to a
    reply is never left out of the question.

    With dev_added (draft set only), the rows are draft-dev-01 onward with
    split "dev" and origin DEV_ADDED_ORIGIN instead, appended after the
    frozen rows, which are never touched.

    Args:
        kind_set (str): "retrieval" or "draft".
        out (str | Path | None): The candidates file (--out); None means
            the set's default file.
        dev_added (bool): Freeze rows added to dev after the set was frozen.

    Returns:
        None.

    Raises:
        SystemExit: If the golden file already holds this set (it is frozen
            once; with dev_added, if it already holds draft-dev rows), there
            are no candidates, any candidate is invalid (all problems are
            listed by candidate id), or dev_added is asked for on the
            retrieval set.

    Side effects: appends to the golden file and adds frozen_at, the row
    count and the split counts to the candidates metadata.
    """
    if dev_added and kind_set != "draft":
        sys.exit("--dev-added is for the draft set only")
    candidates_path, meta_path = _paths(kind_set, out)
    golden_path = GOLDEN[kind_set]
    prefix = DEV_ADDED_PREFIX if dev_added else ID_PREFIX[kind_set]
    golden = [json.loads(line) for line in golden_path.read_text().splitlines() if line.strip()] \
        if golden_path.exists() else []
    # Exactly "<prefix>-<digits>", so draft-dev-01 never counts as the main
    # draft set and the reverse.
    if any(re.fullmatch(rf"{prefix}-\d+", str(row.get("id", ""))) for row in golden):
        sys.exit(f"{_shown(golden_path)} already holds the {prefix} rows; they are frozen")
    if not candidates_path.exists():
        sys.exit(f"No candidates at {_shown(candidates_path)}; run generate first")
    rows = [json.loads(line) for line in candidates_path.read_text().splitlines() if line.strip()]
    if not rows:
        sys.exit("No candidates to freeze")
    guide_ids = {doc["hpa_id"] for doc in load_docs(DOCS_DIR)}
    problems = [f"{row.get('cid', i)}: {problem}" for i, row in enumerate(rows, 1)
                for problem in validate(kind_set, row, guide_ids)]
    if problems:
        sys.exit("Fix these candidates first:\n  " + "\n  ".join(problems))
    out = []
    for n, row in enumerate(rows, 1):
        row_id = f"{prefix}-{n:02d}" if dev_added else f"{prefix}-{n:03d}"
        if kind_set == "retrieval":
            out.append({"id": row_id, "split": split_for(row_id), "query": row["query"].strip(),
                        "expected_hpa_ids": row["expected_hpa_ids"], "origin": "messy", "notes": row.get("notes", "")})
            continue
        frozen = {"id": row_id, "split": "dev" if dev_added else split_for(row_id)}
        if dev_added:
            frozen["origin"] = DEV_ADDED_ORIGIN
        frozen.update({"kind": row["kind"], "channel": row["channel"]})
        if row["kind"] == "clarified":
            rounds = [{"round": r["round"], "prompt": r["prompt"].strip(), "reply": r["reply"].strip()}
                      for r in row["rounds"]]
            frozen.update({"question_text": join_question(row["original_text"].strip(), rounds),
                           "original_text": row["original_text"].strip(), "rounds": rounds})
        else:
            frozen["question_text"] = row["question_text"].strip()
        frozen["safety_flagged"] = row["safety_flagged"]
        if row.get("flagged_topics"):
            frozen["flagged_topics"] = row["flagged_topics"]
        frozen.update({"expected_hpa_ids": row["expected_hpa_ids"], "expected_coverage": row["expected_coverage"],
                       "notes": row.get("notes", "")})
        out.append(frozen)
    with golden_path.open("a") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    splits = {split: sum(row["split"] == split for row in out) for split in ("dev", "test")}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta.update({"frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "frozen_rows": len(out),
                     "splits": splits})
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Froze {len(out)} {kind_set} rows ({splits['dev']} dev, {splits['test']} test) "
          f"into {_shown(golden_path)}")


def main():
    """Parse the command line and run one command.

    Args (command line):
        command        estimate | generate | freeze
        --set S        retrieval | draft (required for generate and freeze;
                       estimate covers both when omitted)
        --seed N       spec mix seed (default 20261030)
        --budget X     hard spend limit in USD (default 2.0)
        --workers N    parallel generator calls (default 4)
        --force        let generate replace an existing candidates file
        --kinds K      generate only these kinds, each optionally =N rows,
                       for example out_of_kb=8 (parse_kinds)
        --out FILE     the candidates file for generate and freeze (default
                       eval/private/kb_candidates_<set>.jsonl)
        --avoid TEXT   topics generate must stay away from; kept on the
                       command line and in the git-ignored metadata only
        --dev-added    freeze the rows as draft-dev-NN dev rows (draft only)

    Returns:
        None.

    Side effects: depends on the command (see the module docstring).
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["estimate", "generate", "freeze"])
    parser.add_argument("--set", dest="kind_set", choices=SETS)
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--budget", type=float, default=2.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--kinds")
    parser.add_argument("--out")
    parser.add_argument("--avoid")
    parser.add_argument("--dev-added", action="store_true")
    args = parser.parse_args()
    if args.command == "estimate":
        estimate([args.kind_set] if args.kind_set else list(SETS))
        return
    if not args.kind_set:
        parser.error(f"{args.command} needs --set retrieval or --set draft")
    if args.command == "generate":
        run(args.kind_set, args.seed, args.budget, args.workers, args.force,
            parse_kinds(args.kinds, args.kind_set), args.out, args.avoid)
    else:
        freeze(args.kind_set, args.out, args.dev_added)


if __name__ == "__main__":
    main()
