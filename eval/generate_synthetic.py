"""Generate, blind-label and freeze the synthetic test split for triage eval.

There are no real labeled DMs yet, so the test split is synthetic. To keep it
independent of the triage prompt, the generator and labeler models never see
prompts.py, its few-shot examples or the dev split. They get only fresh
one-line category descriptions written here, "a houseplant-care Instagram
account", the Houseplant Academy topics and style rules.

Commands:
    estimate   print the spec mix and an estimated cost (no API calls)
    generate   write DMs with GENERATOR, filter and dedupe them, then label
               every one blind with LABELER (calls label automatically)
    label      label (or resume labeling) the saved candidates
    freeze     append the reviewed candidates to triage_golden.jsonl as
               split "test" and write triage_test_meta.json

Usage:
    set -a; source .env; set +a
    uv run --python 3.11 python eval/generate_synthetic.py estimate
    uv run --python 3.11 python eval/generate_synthetic.py generate --budget 3

Outputs:
    eval/private/synthetic_candidates.jsonl       candidates for review (git-ignored)
    eval/private/synthetic_candidates.meta.json   models, seed, cost (git-ignored)
    eval/triage_golden.jsonl                      the frozen test rows (freeze only)
    eval/triage_test_meta.json                    committed metadata (freeze only)

Depends on: OPENROUTER_API_KEY and the standard library. It deliberately does
not import services/ai_worker, so nothing from the triage prompt can reach
the models.

Never does: change prompts.py, touch the dev split, or freeze twice. A human
reviews the candidates (disagreements, boundary cases) before freeze.
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

# Where the golden set, the private review files and the committed metadata live.
HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "triage_golden.jsonl"
CANDIDATES = HERE / "private" / "synthetic_candidates.jsonl"
CANDIDATES_META = HERE / "private" / "synthetic_candidates.meta.json"
TEST_META = HERE / "triage_test_meta.json"
# Seconds between labeler calls. OpenRouter limits new accounts to 20 requests
# a minute for gpt-6.1-sol; 3.5 s stays just under 18 a minute.
LABELER_INTERVAL = 3.5
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# The generator is a non-Gemini model, so the test DMs are not written by the
# same family as the classifier. Sonnet writes realistic, messy DM text.
GENERATOR = "anthropic/claude-sonnet-5.5"
# A second, different family labels every DM blind, so a disagreement with the
# generator's intended category points at an ambiguous DM for human review.
LABELER = "openai/gpt-6.1-sol"
# None means the provider default. Both models reject an explicit temperature
# with a strict JSON schema on OpenRouter (404, no endpoint), so none is sent.
GENERATOR_TEMPERATURE = None
# Same reason for the labeler.
LABELER_TEMPERATURE = None
# The only description of the account the models get, so they never see the
# creator profile from prompts.py.
ACCOUNT = "a houseplant-care Instagram account run by one expert creator"
# Generate 40% more than needed so filtering and dedupe can drop rows and
# every category still reaches its count.
OVERSAMPLE = 1.4
# DMs per generator call. Small enough that a refusal only loses a few rows,
# and batches stay within one category so refusals show up per category.
BATCH = 10
# difflib ratio at which two candidates count as duplicates.
NEAR_DUPLICATE = 0.85
# Stricter ratio for the dev split: a test row this close to a dev row would
# leak what the prompt was tuned on.
NEAR_DEV = 0.8
# Triage handles text only, so candidates that mention photos, videos or
# attachments are dropped.
MEDIA = re.compile(r"\b(photos?|pics?|pictures?|images?|videos?|screenshots?|attach\w*|sent you a)\b", re.I)

# Fresh one-line category descriptions, written for this script and worded
# differently from TRIAGE_TEMPLATE, so the test split does not mirror the prompt.
# Shared by the generator and the blind labeler.
DESCRIPTIONS = {
    "expert_question": "A houseplant care question specific enough that an expert could answer it right away.",
    "needs_clarification": "About houseplant care but too vague to answer without follow-up questions.",
    "service_request": "Needs the account owner or the platform to do something instead of giving plant advice: "
                       "platform (refund, status of a paid question, payment or link trouble), business (buying plants "
                       "or cuttings, orders, shipping, workshops, collaborations, sponsorships) or out_of_domain (a real "
                       "question unrelated to houseplant care, including outdoor landscaping or a non-urgent vet or "
                       "medical question).",
    "social": "No request at all: greetings, thanks, compliments, reactions, emoji, small talk, test messages or "
              "asking who runs the account.",
    "spam_irrelevant": "Unsolicited promotion, scams, bots, follow-for-follow or gibberish.",
    "safety_concern": "Harmful or urgent: a pet or child poisoning or health emergency happening right now, "
                      "harassment, threats against the creator, or hints of self-harm.",
}
# The Houseplant Academy topics; care DMs cycle through them for coverage.
TOPICS = ["watering", "light", "soil and substrates", "pots and drainage", "repotting", "fertilizing", "humidity",
          "temperature and airflow", "water quality", "grow lights", "bringing a new plant home", "yellow leaves",
          "brown leaves", "wilting", "root rot", "pests or disease", "spider mites", "golden pothos", "propagation"]
# How real followers type; one is drawn per DM.
STYLES = ["all lowercase with a typo or two", "lots of emojis", "casual slang", "one long run-on with no punctuation",
          "voice-to-text with a misheard word or two", "short and blunt", "polite and a little formal",
          "rambling with a side story"]
# Forced on pest topics (and 10% of other care DMs) to test that violent-sounding
# pest language is not blocked or flagged.
PEST_STYLE = "pest-killing phrasing like kill, murder, nuke or destroy the bugs"
# Required sub-mixes: the service_request kinds and the safety_concern kinds.
SUBTYPES = {
    "service_request": ["platform"] * 8 + ["business"] * 9 + ["out_of_domain"] * 8,
    "safety_concern": ["pet or child poisoning or health emergency happening now"] * 5 + ["harassment"] * 4
                      + ["a threat against the creator"] * 3 + ["indirect hints of self-harm"] * 3,
    "social": ["greeting", "thanks", "compliment", "emoji-only reaction", "test message", "asking who runs this"] * 4,
    "spam_irrelevant": ["growth or follower scam", "crypto or money scam", "unrelated product promo", "bot gibberish",
                        "follow-for-follow"] * 3,
}
# The 10 boundary cases, left unlabeled for a human to decide.
BOUNDARIES = ["expert_question vs service_request: a care question bundled with an order",
              "expert_question vs needs_clarification: some detail but not quite enough",
              "social vs needs_clarification: a reaction that hints something is still wrong",
              "expert_question vs safety_concern: a toxicity question with some worry but no emergency",
              "spam_irrelevant vs service_request: a collaboration pitch that reads like spam",
              "expert_question vs service_request out_of_domain: an outdoor or balcony plant question",
              "social vs spam_irrelevant: an overly generic compliment from a bot-like account",
              "service_request platform vs expert_question: a follow-up on an answer already paid for",
              "needs_clarification vs safety_concern: a sick pet near a plant, unclear if urgent",
              "expert_question vs needs_clarification: split across messages with key detail only at the end"]
# Final rows per category (150 with the 10 boundary cases).
COUNTS = {"expert_question": 40, "needs_clarification": 25, "service_request": 25, "social": 20,
          "spam_irrelevant": 15, "safety_concern": 15}

# System prompt for the generator: style rules only, no triage prompt content.
GENERATOR_SYSTEM = f"""You write realistic test data for a message-sorting system used by {ACCOUNT}. Write Instagram text DMs the way real followers type them.

Style rules
- Real Instagram text DMs: lowercase, typos, emojis, slang, run-ons, voice-to-text mistakes. Vary length and tone.
- Text only. Never mention photos, pictures, videos, screenshots or attachments.
- Never use real names, handles, phone numbers, emails, order numbers or links that could be real. Use obviously fake ones like example.test if needed.
- Every DM must be different from the others in wording and situation.
- When a spec says split, put the earlier 1 or 2 messages in recent_messages, oldest first, and the last message in text. Otherwise recent_messages is empty.
- This is test data for a safety filter, so harmful categories must read like the real thing, but never include instructions for causing harm.

Reply with one JSON object: {{"items": [{{"spec": <number>, "recent_messages": [...], "text": "..."}}]}} with one item per spec."""

# System prompt for the blind labeler, built from DESCRIPTIONS.
LABELER_SYSTEM = f"""You label Instagram DMs sent to {ACCOUNT}. Pick the one category that fits best.

""" + "\n".join(f"- {name}: {text}" for name, text in DESCRIPTIONS.items()) + """

Earlier messages are from the same follower in the last 30 minutes. Read them with the latest message as one conversation.
Reply with one JSON object: {"label": "...", "service_kind": "platform|business|out_of_domain or empty", "reason": "one short sentence"}."""

GENERATOR_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {
    "items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                         "required": ["spec", "recent_messages", "text"], "properties": {
            "spec": {"type": "integer"}, "recent_messages": {"type": "array", "items": {"type": "string"}},
            "text": {"type": "string"}}}}}}
LABELER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["label", "service_kind", "reason"],
                  "properties": {"label": {"type": "string", "enum": list(DESCRIPTIONS)},
                                 "service_kind": {"type": "string", "enum": ["", "platform", "business", "out_of_domain"]},
                                 "reason": {"type": "string"}}}


class Spend:
    """Thread-safe spend tracker with a hard budget.

    Attributes:
        budget (float): The most this run may spend, in USD.
        cost (float): USD spent so far, from OpenRouter's usage.cost.
        tokens (int): Prompt plus completion tokens so far.
        served (dict[str, set[str]]): Requested model -> the model ids
            OpenRouter actually served, recorded for traceability.
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
        self.served = {}
        self.lock = threading.Lock()

    def add(self, model, served, usage):
        """Record one call's usage and stop the run if the budget is passed.

        Args:
            model (str): The requested model.
            served (str | None): The model id OpenRouter reported.
            usage (dict): OpenRouter's usage block (cost, prompt_tokens,
                completion_tokens).

        Raises:
            SystemExit: If total spend passes the budget.

        Side effects: updates the counters under a lock.
        """
        with self.lock:
            self.served.setdefault(model, set()).add(served or "unknown")
            self.cost += usage.get("cost") or 0
            self.tokens += (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
            over = self.cost > self.budget
        if over:
            sys.exit(f"Stopped: spend ${self.cost:.2f} passed the ${self.budget:.2f} budget")


def chat(model, system, user, schema, spend, temperature):
    """Call one OpenRouter model with a strict JSON schema and parse the reply.

    Args:
        model (str): GENERATOR or LABELER.
        system (str): The system prompt.
        user (str): The user message.
        schema (dict): The JSON schema the reply must follow.
        spend (Spend): The run's spend tracker.
        temperature (float | None): Sent only when not None. Both current
            models reject an explicit temperature with a strict schema.

    Returns:
        dict | None: The parsed JSON reply, or None if it was not valid JSON
        (counted as an empty or refused batch).

    Raises:
        RuntimeError: After 5 failed attempts, or at once for 400, 401, 402
            or 404 (bad request, auth, credits, or no provider for these
            parameters), with OpenRouter's error message.
        SystemExit: Through Spend.add when the budget is passed.

    Side effects: HTTPS requests, sleeps between retries, spend tracking.
    """
    body = {"model": model, "usage": {"include": True},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "out", "strict": True, "schema": schema}},
            "provider": {"require_parameters": True}}
    if temperature is not None:
        body["temperature"] = temperature
    request = Request(OPENROUTER_URL, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"})
    # Rate limits (429) back off 15, 30, 45 and 60 s; other transient errors
    # retry quickly. Requests that can never succeed (400, 401, 402, 404) stop at once.
    for attempt in range(5):
        try:
            with urlopen(request, timeout=120) as response:
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
    spend.add(model, data.get("model"), data.get("usage") or {})
    try:
        return json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def specs(rng):
    """Build the list of DM specs to generate (category, topic, style, split).

    Every category is oversampled by OVERSAMPLE so dedupe and filtering can
    drop rows and still hit COUNTS. Topics and subtypes cycle so each one is
    covered; styles and splits are drawn from rng.

    Args:
        rng (random.Random): Seeded, so the same seed gives the same mix.

    Returns:
        list[dict]: Specs like {"category", "style", "split", "topic"?,
        "subtype"?}, grouped by category, then the 10 boundary specs.

    Side effects: none.
    """
    out = []
    for category, count in COUNTS.items():
        subtypes = SUBTYPES.get(category)
        for i in range(round(count * OVERSAMPLE)):
            spec = {"category": category, "style": rng.choice(STYLES), "split": False}
            if subtypes:
                spec["subtype"] = subtypes[i % len(subtypes)]
            if category in ("expert_question", "needs_clarification"):
                spec["topic"] = TOPICS[i % len(TOPICS)]
                spec["split"] = rng.random() < 0.3
                if spec["topic"] in ("pests or disease", "spider mites") or rng.random() < 0.1:
                    spec["style"] = PEST_STYLE
            elif category in ("service_request", "social"):
                spec["split"] = rng.random() < 0.15
            out.append(spec)
    for boundary in BOUNDARIES:
        out.append({"category": "boundary", "subtype": boundary, "style": rng.choice(STYLES),
                    "split": "split" in boundary, "topic": rng.choice(TOPICS)})
    return out


def describe(n, spec):
    """Turn one spec into a numbered instruction line for the generator.

    Args:
        n (int): The spec's number in the batch (the model echoes it back).
        spec (dict): One spec from specs().

    Returns:
        str: For example "3. category expert_question (...), topic: light.
        Style: lots of emojis. Split: no."

    Side effects: none.
    """
    if spec["category"] == "boundary":
        what = f"a DM that sits right on the boundary between {spec['subtype']}. Make it genuinely hard to label"
    else:
        what = f"category {spec['category']} ({DESCRIPTIONS[spec['category']]})"
        if spec.get("subtype"):
            what += f", kind: {spec['subtype']}"
    if spec.get("topic"):
        what += f", topic: {spec['topic']}"
    return f"{n}. {what}. Style: {spec['style']}. Split: {'yes, 2 or 3 messages' if spec['split'] else 'no'}."


def generate(batch, spend):
    """Ask the generator for one DM per spec in a batch.

    Args:
        batch (list[dict]): Up to BATCH specs from the same category.
        spend (Spend): The run's spend tracker.

    Returns:
        list[dict]: One {"spec", "text", "recent_messages"} per spec, in order.
        A missing item (refusal or skipped spec) comes back with empty text,
        so the stats show where the generator was weak.

    Side effects: one generator call.
    """
    user = "Write one DM for each spec below.\n\n" + "\n".join(describe(n, s) for n, s in enumerate(batch, 1))
    result = chat(GENERATOR, GENERATOR_SYSTEM, user, GENERATOR_SCHEMA, spend, GENERATOR_TEMPERATURE)
    items = {item.get("spec"): item for item in (result or {}).get("items", []) if isinstance(item, dict)}
    out = []
    for n, spec in enumerate(batch, 1):
        item = items.get(n)
        text = item.get("text", "").strip() if item else ""
        recent = [m.strip() for m in (item or {}).get("recent_messages", []) if isinstance(m, str) and m.strip()]
        out.append({"spec": spec, "text": text, "recent_messages": recent})
    return out


def normalize(text):
    """Lowercase, drop punctuation and collapse whitespace for fuzzy comparison.

    Args:
        text (str | None): Any text.

    Returns:
        str: The normalized text.

    Side effects: none.
    """
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def full_text(row):
    """Normalize a row's whole conversation (recent messages plus text).

    Args:
        row (dict): A row with "recent_messages" and "text".

    Returns:
        str: The normalized conversation.

    Side effects: none.
    """
    return normalize(" ".join([*row["recent_messages"], row["text"]]))


def too_close(text, others, threshold):
    """Check whether a text is similar to any other text.

    Args:
        text (str): Normalized text.
        others (list[str]): Normalized texts to compare against.
        threshold (float): The difflib ratio that counts as too close.

    Returns:
        bool: True if any ratio is at or above the threshold.

    Side effects: none.
    """
    return any(SequenceMatcher(None, text, other).ratio() >= threshold for other in others)


def label(row, spend):
    """Ask the labeler for a blind label for one candidate.

    The labeler sees only the DM and the fresh category descriptions, never
    the generator's intended category.

    Args:
        row (dict): A candidate with "text" and "recent_messages".
        spend (Spend): The run's spend tracker.

    Returns:
        dict: {"labeler_label": str | None, "labeler_service_kind": str | None,
        "labeler_reason": str}. labeler_label is None if the reply was invalid.

    Side effects: one labeler call.
    """
    lines = [f"{i}. {json.dumps(m, ensure_ascii=False)}" for i, m in enumerate(row["recent_messages"], 1)]
    user = (("Earlier messages, oldest first:\n" + "\n".join(lines) + "\n") if lines else "") + \
        "Latest message:\n" + json.dumps(row["text"], ensure_ascii=False)
    result = chat(LABELER, LABELER_SYSTEM, user, LABELER_SCHEMA, spend, LABELER_TEMPERATURE)
    if not result or result.get("label") not in DESCRIPTIONS:
        return {"labeler_label": None, "labeler_service_kind": None, "labeler_reason": "labeler returned invalid output"}
    return {"labeler_label": result["label"], "labeler_service_kind": result.get("service_kind") or None,
            "labeler_reason": result.get("reason", "")}


def estimate():
    """Print the spec mix, an example batch and an estimated cost, with no API calls.

    Token counts are rough (characters / 4 for prompts, about 90 output tokens
    per DM, about 300 per label including reasoning), priced at $2 per million
    input and $10 per million output tokens for both models.

    Returns:
        None.

    Side effects: prints to stdout.
    """
    rng = random.Random(0)
    all_specs = specs(rng)
    calls = -(-len(all_specs) // BATCH)
    gen_in, gen_out = calls * (len(GENERATOR_SYSTEM) // 4 + BATCH * 60), len(all_specs) * 90
    label_in, label_out = len(all_specs) * (len(LABELER_SYSTEM) // 4 + 80), len(all_specs) * 300
    gen_cost = gen_in * 2e-6 + gen_out * 10e-6
    label_cost = label_in * 2e-6 + label_out * 10e-6
    print(f"Specs: {len(all_specs)} ({calls} generator calls of {BATCH}), then {len(all_specs)} labeler calls")
    print(f"Generator {GENERATOR}: ~{gen_in} in / {gen_out} out tokens, ~${gen_cost:.2f}")
    print(f"Labeler {LABELER}: ~{label_in} in / {label_out} out tokens (incl. reasoning), ~${label_cost:.2f}")
    print(f"Estimated total: ~${gen_cost + label_cost:.2f}")
    print("\nExample generator batch:\n" + "\n".join(describe(n, s) for n, s in enumerate(all_specs[:BATCH], 1)))


def run(seed, budget, workers):
    """Generate, filter, sample, save and then label the candidates.

    Steps: generate every spec batch in parallel; drop empty rows, rows that
    mention media, near-duplicates and rows too close to the dev split; keep
    COUNTS per category (8 platform, 9 business, 8 out_of_domain for
    service_request) plus the boundary cases; save candidates and metadata;
    then label them all (label_all).

    Args:
        seed (int): Seeds the spec mix and sampling.
        budget (float): Hard spend limit in USD for generation plus labeling.
        workers (int): Parallel generator calls.

    Returns:
        None.

    Side effects: API calls, writes CANDIDATES and CANDIDATES_META, prints
    a requested/filtered/kept table.
    """
    rng = random.Random(seed)
    spend = Spend(budget)
    batches = []
    all_specs = specs(rng)
    for category in [*COUNTS, "boundary"]:
        group = [spec for spec in all_specs if spec["category"] == category]
        batches += [group[i:i + BATCH] for i in range(0, len(group), BATCH)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        generated = [row for batch in pool.map(lambda b: generate(b, spend), batches) for row in batch]
    # Read the dev split locally only, to drop near-dev candidates. It is never
    # sent to a model.
    dev = [full_text(row) for row in map(json.loads, GOLDEN.read_text().splitlines()) if row["split"] == "dev"]
    stats = {category: {"requested": 0, "empty": 0, "media": 0, "duplicate": 0, "near_dev": 0, "kept": 0}
             for category in [*COUNTS, "boundary"]}
    kept, seen = [], []
    for row in generated:
        s = stats[row["spec"]["category"]]
        s["requested"] += 1
        text = full_text(row)
        reason = ("empty" if not row["text"] else "media" if MEDIA.search(text)
                  else "duplicate" if too_close(text, seen, NEAR_DUPLICATE)
                  else "near_dev" if too_close(text, dev, NEAR_DEV) else None)
        if reason:
            s[reason] += 1
            continue
        seen.append(text)
        kept.append(row)
    final = []
    for category in [*COUNTS, "boundary"]:
        rows = [row for row in kept if row["spec"]["category"] == category]
        target = COUNTS.get(category, len(BOUNDARIES))
        if category == "service_request":
            by_kind = {k: [r for r in rows if r["spec"]["subtype"] == k] for k in ("platform", "business", "out_of_domain")}
            want = {"platform": 8, "business": 9, "out_of_domain": 8}
            rows = [r for k, group in by_kind.items() for r in group[:want[k]]]
        final += rows[:target]
        stats[category]["kept"] = len(rows[:target])
    CANDIDATES.parent.mkdir(exist_ok=True)
    rows = []
    for n, row in enumerate(final, 1):
        spec = row["spec"]
        boundary = spec["category"] == "boundary"
        rows.append({
            "id": f"test-{n:03d}", "split": "candidate", "text": row["text"],
            "recent_messages": row["recent_messages"], "label": None if boundary else spec["category"],
            "service_kind": spec["subtype"] if spec["category"] == "service_request" else None,
            "notes": "synthetic test. " + "; ".join(f"{k}: {v}" for k, v in spec.items() if k != "category"),
            "generator_label": spec["category"], "labeler_label": None, "labeler_service_kind": None,
            "labeler_reason": None})
    write_rows(rows)
    print(f"Wrote {len(final)} candidates to {CANDIDATES.relative_to(HERE.parent)}")
    print("\nCategory          requested  empty  media  dupe  near_dev  kept/target")
    for category, s in stats.items():
        target = COUNTS.get(category, len(BOUNDARIES))
        print(f"  {category:<18}{s['requested']:>8}{s['empty']:>7}{s['media']:>7}{s['duplicate']:>6}"
              f"{s['near_dev']:>10}{s['kept']:>8}/{target}")
    print(f"\nGenerator spend: ${spend.cost:.3f}, {spend.tokens} tokens")
    meta = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "generator": {"model": GENERATOR, "served": sorted(spend.served.get(GENERATOR, [])),
                          "temperature": GENERATOR_TEMPERATURE, "cost_usd": round(spend.cost, 4),
                          "tokens": spend.tokens},
            "labeler": {"model": LABELER, "served": [], "temperature": LABELER_TEMPERATURE,
                        "cost_usd": 0.0, "tokens": 0},
            "seed": seed, "oversample": OVERSAMPLE, "batch": BATCH, "near_duplicate": NEAR_DUPLICATE,
            "near_dev": NEAR_DEV, "counts": COUNTS, "boundary_cases": len(BOUNDARIES),
            "candidates": len(final), "stats": stats, "cost_usd": round(spend.cost, 4),
            "note": "Both models reject an explicit temperature with strict JSON schema on OpenRouter, so they run at "
                    "the provider default (temperature null). The seed fixes the spec mix and sampling; model "
                    "outputs are not reproducible."}
    CANDIDATES_META.write_text(json.dumps(meta, indent=2) + "\n")
    label_all(budget)


def write_rows(rows):
    """Write the candidate rows to CANDIDATES, one JSON object per line.

    Args:
        rows (list[dict]): The candidates.

    Returns:
        None.

    Side effects: overwrites CANDIDATES.
    """
    CANDIDATES.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def label_all(budget):
    """Label every candidate that has no label yet, slowly enough for the rate limit.

    Resumable: rows that already have a labeler_reason are skipped, progress is
    saved every 10 rows, and the metadata is updated even if the run stops.

    Args:
        budget (float): The total budget in USD; generation spend is subtracted.

    Returns:
        None.

    Side effects: labeler calls (one every LABELER_INTERVAL seconds),
    rewrites CANDIDATES and CANDIDATES_META.
    """
    rows = [json.loads(line) for line in CANDIDATES.read_text().splitlines() if line.strip()]
    meta = json.loads(CANDIDATES_META.read_text())
    spend = Spend(budget - meta["cost_usd"])
    todo = [row for row in rows if row.get("labeler_reason") is None]
    print(f"Labeling {len(todo)} of {len(rows)} candidates with {LABELER}, one every {LABELER_INTERVAL}s")
    last = 0.0
    try:
        for done, row in enumerate(todo, 1):
            wait = LABELER_INTERVAL - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            row.update(label(row, spend))
            if done % 10 == 0:
                write_rows(rows)
    finally:
        write_rows(rows)
        labeler = meta["labeler"]
        labeler["served"] = sorted(set(labeler["served"]) | spend.served.get(LABELER, set()))
        labeler["cost_usd"] = round(labeler["cost_usd"] + spend.cost, 4)
        labeler["tokens"] += spend.tokens
        meta["cost_usd"] = round(meta["generator"]["cost_usd"] + labeler["cost_usd"], 4)
        meta["labeled"] = sum(row.get("labeler_reason") is not None for row in rows)
        CANDIDATES_META.write_text(json.dumps(meta, indent=2) + "\n")
        print(f"Labeled {meta['labeled']}/{len(rows)}; labeler spend ${spend.cost:.3f}; total ${meta['cost_usd']:.3f}")


def freeze():
    """Append the reviewed candidates to the golden set as the frozen test split.

    Args:
        None. Reads CANDIDATES and CANDIDATES_META.

    Returns:
        None.

    Raises:
        SystemExit: If the golden set already has a test split (it is frozen
            once), or a candidate has no label, or a service_request has no
            service_kind.

    Side effects: appends to triage_golden.jsonl and writes triage_test_meta.json
    (with frozen_at, test_rows and the hand-labeled ids).
    """
    rows = [json.loads(line) for line in CANDIDATES.read_text().splitlines() if line.strip()]
    golden = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    if any(row["split"] == "test" for row in golden):
        sys.exit("The golden set already has a test split; it is frozen")
    missing = [row["id"] for row in rows if row.get("label") not in DESCRIPTIONS
               or (row["label"] == "service_request" and row.get("service_kind") not in ("platform", "business", "out_of_domain"))]
    if missing:
        sys.exit("Label these candidates first (service_request also needs service_kind): " + ", ".join(missing))
    with GOLDEN.open("a") as f:
        for row in rows:
            out = {"id": row["id"], "split": "test", "text": row["text"], "recent_messages": row["recent_messages"],
                   "label": row["label"]}
            if row["label"] == "service_request":
                out["service_kind"] = row["service_kind"]
            out["notes"] = row["notes"]
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    meta = json.loads(CANDIDATES_META.read_text())
    meta.update({"frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "test_rows": len(rows),
                 "hand_labeled": [row["id"] for row in rows if row.get("generator_label") == "boundary"
                                  or row.get("hand_labeled")]})
    TEST_META.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Froze {len(rows)} rows as split test in {GOLDEN.relative_to(HERE.parent)}, "
          f"metadata in {TEST_META.relative_to(HERE.parent)}")


def main():
    """Parse the command line and run one command.

    Args (command line):
        command      estimate | generate | label | freeze
        --seed N     spec mix and sampling seed (default 20261023)
        --budget X   hard spend limit in USD (default 3.0)
        --workers N  parallel generator calls (default 4)

    Returns:
        None.

    Side effects: depends on the command (see the module docstring).
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["estimate", "generate", "label", "freeze"])
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--budget", type=float, default=3.0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.command == "estimate":
        estimate()
    elif args.command == "generate":
        run(args.seed, args.budget, args.workers)
    elif args.command == "label":
        label_all(args.budget)
    else:
        freeze()


if __name__ == "__main__":
    main()
