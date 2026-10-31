"""Grounded answer drafts for paid questions.

This module turns one paid question (with its clarification rounds) into a
single decision dict: a reply the creator edits before sending, written only
from passages of the creator's own guides, or the reason there is no draft.
A draft only helps the creator; whatever the outcome, the question still
goes to the creator.

Entry point:
    draft(question_text, *, creator_id, rounds=None, original_text=None,
          channel="instagram", safety_flagged=False, flagged_topics=None,
          profile=None, search=None, time_left=None)
        Called by the worker for each draft job (README "For Akshay").

Flow (spec 6.5 with 14.3 and 14.7):
    empty question -> no_draft; build the search query; retrieve guide
    chunks; similarity gate -> no_draft without a model call; number the
    passages and build this call's schema; write, with one retry on invalid
    output; clip missing_info; coverage "none" -> no_draft; checkpoint 2
    (safety.screen on the answer); citations.

Depends on:
    llm        write_draft (the model call), moderate (checkpoint 2),
               MIN_SECONDS_FOR_CALL and the error types. Tests replace this
               module with a fake.
    knowledge  search, the default retrieval, looked up at call time.
    safety     screen and flag, shared with triage's checkpoint 1.
    prompts    the default profile, draft_prompt, answer_char_target and the
               version strings.

Never does:
    - Make HTTP calls itself, read or write the database, or send DMs. The
      worker stores the decision as one drafts row plus its safety_flags.
    - Turn an LLMError or RuntimeError into a decision. An outage propagates
      so the job retries; a missing key is a configuration alert.
    - Send a rejected answer back to the model. The retry only names what
      failed, from the fixed RETRY_REASONS table.
    - Log question, reply, passage, answer or missing_info text, or keys.
      The one log line carries status, reason, coverage, counts, the best
      similarity, error codes, attempts, latency, tokens and cost.
"""

import json
import logging
import re
import time

import knowledge
import llm
import safety
from prompts import DRAFT_VERSION, SWEETLIFE_FLORA, answer_char_target, draft_prompt, prompt_version


# Below this best cosine similarity, retrieval found nothing close enough to
# draft from: no_draft with reason no_coverage and no model call. It gates on
# similarity, never on the RRF score: score only measures rank position, so
# the best row of any query scores high.
# 2026-10-30, tuned on dev, frozen (eval_draft.py --gate-sweep, offline). On
# the 17 dev rows the 5 out-of-KB rows peak at 0.465 and the 12 answerable
# rows start at 0.515. 0.475 is the lowest cutoff that stops all 5 out-of-KB
# rows while stopping 0 of 12 answerable ones (0.450 stops 2 of 5; 0.500 also
# stops 5 and 0, and the tie goes to the lower cutoff, because a row past the
# gate can still end as no_draft through the model's coverage "none", while
# an answerable row stopped here loses its draft). The start value was 0.30
# (spec 14.6). Change it only after a new dev sweep, never because of a test
# row.
DRAFT_MIN_SIMILARITY = 0.475

# Passages retrieved per draft (spec 6.5 step 3). Eight chunks of 300 to 500
# tokens are enough for a question that spans two guides and keep the call
# near the $0.02 per draft target.
SEARCH_K = 8

# Version 1 drafts from the Academy guides only (spec 14.2 Q9), so a draft
# never cites the 8 demo Q&A answers the team wrote. Add "question" once real
# answered Q&A exist (flow 6).
SEARCH_SOURCES = ("doc",)

# Characters of search query kept (spec 6.5 step 2). A question plus its
# replies is rarely longer; the cap stops a pasted wall of text from swamping
# the embedding and the full-text query.
QUERY_MAX_CHARS = 2000

# missing_info is clipped, never a failure (spec 14.3 Q14): at most this many
# topic phrases, each at most MISSING_INFO_CHARS, so the "what the guides
# don't cover" list stays short enough to scan in the inbox.
MAX_MISSING_INFO = 5
MISSING_INFO_CHARS = 80

# The knowledge_coverage values the model may return (the schema enum).
COVERAGES = ("high", "partial", "none")

# Pattern checks on the answer, applied in this order after the empty and
# length checks; the first match is the error code for the retry. They
# enforce the template's Format rules (spec 14.3 Q13 and 14.10):
# - markdown: a line starting with "#" after optional spaces, any "*" or any
#   backtick. "- " bullets and "1." steps are allowed.
# - url: "http://", "https://" or "www.", any case.
# - ref_marker: "[K", a passage ref copied into the text.
# - citation_marker: "[" then a digit, such as "[1]" or "[1-3]".
# - internal_id: a guide id such as "HPA-FUND-0001" or "FUND-0001", the same
#   pattern chunk.replace_ids removes from chunk text. Checked against all 368
#   staged chunks before B2: no normal word or measurement matches.
# - banned_word: "AI" as a whole word (case-sensitive, so "said" or "Ai" never
#   match), "passage(s)" or "knowledge base" in any case. "source" is allowed.
ANSWER_CHECKS = (
    ("markdown", re.compile(r"^[ \t]*#|[*`]", re.MULTILINE)),
    ("url", re.compile(r"https?://|www\.", re.IGNORECASE)),
    ("ref_marker", re.compile(r"\[K")),
    ("citation_marker", re.compile(r"\[\d")),
    ("internal_id", re.compile(r"\b(?:HPA-)?[A-Z]{3,8}-\d{4}\b")),
    ("banned_word", re.compile(r"\bAI\b|(?i:\bpassages?\b|\bknowledge\s+base)")),
)

# The one fixed retry reason per error code (spec 14.7 Q3). The retry tells
# the model what failed without echoing the question or its rejected answer.
# {char_target} is the channel's answer_char_target.
RETRY_REASONS = {
    "not_json": "the reply was not valid JSON matching the schema",
    "bad_fields": "the reply was not valid JSON matching the schema",
    "empty_answer": "the answer was empty",
    "too_long": "too long, keep it under {char_target} characters",
    "markdown": "it used markdown; use plain text with no headings, asterisks or backticks",
    "url": "it contained a link; remove all links",
    "ref_marker": "it put passage markers in the answer; remove them",
    "citation_marker": "it contained citation numbers like [1]; remove them",
    "internal_id": "it contained an internal guide id; remove it",
    "banned_word": "it mentioned AI, passages or a knowledge base; remove that",
    "unknown_ref": "it cited a passage that was not provided; use only the given refs",
    "no_sources": "it listed no passages; list the passages you used",
    "bad_risk_topic": "it listed a risk topic that is not in the list",
}

# The last line of the retry's user message.
RETRY_LINE = "Your previous reply was rejected: {reason}. Return a corrected reply."

# The clock the deadline is measured on: time.monotonic, the same clock
# llm.write_draft checks by default. Module-level so tests can replace it.
_clock = time.monotonic

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _rounds(rounds):
    """Clean and sort the clarification rounds.

    Args:
        rounds (list[dict] | None): clarification_rounds rows
            [{"round": int, "prompt": str, "reply": str | None}], any order.

    Returns:
        list[dict]: [{"round", "prompt", "reply"}] sorted by round, with a
        missing prompt as "" and the reply stripped ("" when missing).

    Side effects: none.
    """
    return [{"round": item["round"], "prompt": item.get("prompt") or "",
             "reply": item["reply"].strip() if isinstance(item.get("reply"), str) else ""}
            for item in sorted(rounds or [], key=lambda item: item["round"])]


def _note(safety_flagged, topics):
    """Build the risk note line for a flagged question (spec 14.3 Q15, 14.7 Q4).

    Args:
        safety_flagged (bool): questions.safety_flagged.
        topics (list[str]): Checkpoint-1 risk topics, already limited to the
            profile's list.

    Returns:
        str | None: The line after "Note: ", or None when not flagged. Topics
        are a fixed vocabulary, so they are written plainly, not quoted.

    Side effects: none.
    """
    if not safety_flagged:
        return None
    if topics:
        return f"This question was flagged for these risk topics: {'; '.join(topics)}. Include the caution."
    return "This question was flagged for a possible risk topic; check the risk topics and include the caution if one applies."


def _user_message(question, original, rounds, note, passages):
    """Render the question, its context and the passages as the user message.

    Every external text (question, original message, rounds, passage titles
    and content) is JSON-quoted, like triage's _conversation, so the model
    sees exactly where data starts and ends.

    Args:
        question (str): The final question text, stripped.
        original (str): The original DM, or "" to leave its block out.
        rounds (list[dict]): _rounds() output.
        note (str | None): _note() output.
        passages (list[tuple[str, dict]]): (ref, search result) pairs.

    Returns:
        str: Lines like:
            Final question:
            "..."
            Original message:        (only when original is set)
            "..."
            Clarification:           (only with rounds)
            Round 1 question: "..."
            Round 1 reply: "..."
            Note: ...                (only when flagged)
            Passages:
            [K1] "<title>"
            "<content>"

    Side effects: none.
    """
    def quote(text):
        """JSON-quote one text, keeping non-ASCII characters readable."""
        return json.dumps(text or "", ensure_ascii=False)

    lines = ["Final question:", quote(question)]
    if original:
        lines += ["Original message:", quote(original)]
    if rounds:
        lines.append("Clarification:")
        for item in rounds:
            lines.append(f"Round {item['round']} question: {quote(item['prompt'])}")
            lines.append(f"Round {item['round']} reply: {quote(item['reply'])}")
    if note:
        lines.append(f"Note: {note}")
    lines.append("Passages:")
    for ref, result in passages:
        lines += [f"[{ref}] {quote(result.get('title'))}", quote(result.get("content"))]
    return "\n".join(lines)


def _schema(refs, profile):
    """Build the strict output schema for one draft call (spec 6.5 step 5).

    Built per call because the ref enum is exactly the refs sent, and the
    risk_topics enum is the creator's list, so a flag can never hold text.

    Args:
        refs (list[str]): The passage refs sent, "K1" to "Kn".
        profile (dict): The creator profile (risk_topics).

    Returns:
        dict: A JSON schema requiring answer, used_sources [{ref, supports}],
        knowledge_coverage, missing_info and risk_topics.

    Side effects: none.
    """
    return {
        "type": "object", "additionalProperties": False,
        "required": ["answer", "used_sources", "knowledge_coverage", "missing_info", "risk_topics"],
        "properties": {
            "answer": {"type": "string"},
            "used_sources": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["ref", "supports"],
                "properties": {"ref": {"type": "string", "enum": list(refs)}, "supports": {"type": "string"}}}},
            "knowledge_coverage": {"type": "string", "enum": list(COVERAGES)},
            "missing_info": {"type": "array", "items": {"type": "string"}},
            "risk_topics": {"type": "array", "items": {"type": "string", "enum": list(profile["risk_topics"])}},
        },
    }


def _strings(value):
    """Say whether a value is a list of strings.

    Args:
        value (Any): The field from the model's JSON.

    Returns:
        bool: True for a list (possibly empty) whose items are all str.

    Side effects: none.
    """
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _check(data, refs, profile, channel):
    """Validate one model reply, stopping at the first failure (spec 6.5 step 7).

    The field checks always run first, even when knowledge_coverage says
    "none", because the coverage value can only be trusted once the fields
    are valid. Only after that does coverage "none" skip the answer checks
    (no answer will be used).

    Args:
        data (Any): The parsed JSON from llm.write_draft.
        refs (list[str]): The passage refs sent.
        profile (dict): The creator profile (max_answer_bytes, risk_topics).
        channel (str): "instagram" or "knowledge_app".

    Returns:
        str | None: None when valid, otherwise the error code, one of
        RETRY_REASONS' keys, checked in this order: not_json, bad_fields,
        empty_answer, too_long, the ANSWER_CHECKS codes, unknown_ref,
        no_sources, bad_risk_topic.

    Side effects: none.
    """
    if not isinstance(data, dict):
        return "not_json"
    sources = data.get("used_sources")
    if not (isinstance(data.get("answer"), str) and isinstance(sources, list)
            and all(isinstance(item, dict) and isinstance(item.get("ref"), str)
                    and isinstance(item.get("supports"), str) for item in sources)
            and data.get("knowledge_coverage") in COVERAGES
            and _strings(data.get("missing_info")) and _strings(data.get("risk_topics"))):
        return "bad_fields"
    if data["knowledge_coverage"] == "none":
        return None
    answer = data["answer"].strip()
    if not answer:
        return "empty_answer"
    # Instagram's limit is in bytes, so an accented letter or emoji counts
    # double or more.
    if len(answer.encode("utf-8")) > profile["max_answer_bytes"][channel]:
        return "too_long"
    for code, pattern in ANSWER_CHECKS:
        if pattern.search(answer):
            return code
    if any(item["ref"] not in refs for item in sources):
        return "unknown_ref"
    if not sources:
        return "no_sources"
    if any(topic not in profile["risk_topics"] for topic in data["risk_topics"]):
        return "bad_risk_topic"
    return None


def _write(system, user, schema, refs, profile, channel, deadline, usage):
    """Call the model, with one retry when the reply is invalid.

    The retry is a full write_draft call (primary, then fallback on an
    outage) with the same system prompt and the user message plus
    RETRY_LINE naming what failed. It does not start when a deadline is set
    and fewer than llm.MIN_SECONDS_FOR_CALL seconds remain.

    Args:
        system (str): The rendered draft prompt.
        user (str): _user_message() output.
        schema (dict): _schema() output.
        refs (list[str]): The passage refs sent.
        profile (dict): The creator profile.
        channel (str): "instagram" or "knowledge_app".
        deadline (float | None): Absolute _clock() value, or None for no limit.
        usage (dict): {"attempts": int, "metas": list, "codes": list},
            updated in place: one attempt per call made, each call's meta
            (when it answered) and each failure's error code.

    Returns:
        dict | None: The first valid reply's data, or None after two invalid
        replies, or one invalid reply with no time left for the retry.

    Raises:
        llm.LLMError: From write_draft, including ("openrouter", None,
            "deadline") when the first call cannot start in time.
        RuntimeError: If OPENROUTER_API_KEY is missing.

    Side effects: one or two write_draft calls.
    """
    message = user
    for attempt in (1, 2):
        if attempt == 2 and deadline is not None and deadline - _clock() < llm.MIN_SECONDS_FOR_CALL:
            return None
        usage["attempts"] += 1
        try:
            data, meta = llm.write_draft(system, message, schema, deadline=deadline)
        except llm.InvalidOutput:
            # write_draft only raises it for a reply that is not a JSON object.
            code = "not_json"
        else:
            usage["metas"].append(meta)
            code = _check(data, refs, profile, channel)
        if code is None:
            return data
        usage["codes"].append(code)
        reason = RETRY_REASONS[code].format(char_target=answer_char_target(profile, channel))
        message = f"{user}\n{RETRY_LINE.format(reason=reason)}"
    return None


def _cut(text, limit=MISSING_INFO_CHARS):
    """Cut a phrase to at most limit characters at a word boundary.

    Args:
        text (str): One missing_info phrase, already single-spaced.
        limit (int): Most characters kept.

    Returns:
        str: text unchanged when it fits; otherwise everything before the
        last space within the limit, or a hard cut when the first word alone
        is longer than the limit.

    Side effects: none.
    """
    if len(text) <= limit:
        return text
    space = text.rfind(" ", 0, limit + 1)
    return text[:space] if space > 0 else text[:limit]


def _clip_missing(items):
    """Clip the model's missing_info (spec 14.3 Q14); never a failure.

    Args:
        items (list[str]): The model's missing_info.

    Returns:
        list[str]: Each item stripped (runs of whitespace become one space),
        empties dropped, duplicates dropped ignoring case (first one kept),
        the first MAX_MISSING_INFO kept, each cut by _cut.

    Side effects: none.
    """
    kept, seen = [], set()
    for item in items:
        text = " ".join(item.split())
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        kept.append(text)
    return [_cut(text) for text in kept[:MAX_MISSING_INFO]]


def _citations(used_sources, passages):
    """Map the model's used_sources to stored citations (BASELINE 2.4 shape plus extras).

    Args:
        used_sources (list[dict]): [{"ref": "K2", "supports": str}], refs
            already validated.
        passages (list[tuple[str, dict]]): (ref, search result) pairs sent.

    Returns:
        list[dict]: One {"kind": "knowledge", "ref": entry_id, "title",
        "hpa_id", "supports"} per ref, in order of first use; a ref listed
        twice keeps its first supports text.

    Side effects: none.
    """
    by_ref = dict(passages)
    citations, seen = [], set()
    for item in used_sources:
        if item["ref"] in seen:
            continue
        seen.add(item["ref"])
        result = by_ref[item["ref"]]
        citations.append({"kind": "knowledge", "ref": result["entry_id"], "title": result["title"],
                          "hpa_id": result["hpa_id"], "supports": item["supports"].strip()})
    return citations


def _decision(status, profile, *, reason=None, ai_text=None, citations=(), coverage="none", missing_info=(),
              safety_flags=(), model=None, retrieved=()):
    """Assemble the decision dict draft() returns (spec 6.5).

    Every decision has the same keys, so the worker never checks for a
    missing field.

    Args:
        status (str): "drafted" or "no_draft".
        profile (dict): The creator profile, for prompt_version.
        reason (str | None): None when drafted, otherwise "no_coverage",
            "invalid_output", "safety_blocked" or "empty_question".
        ai_text (str | None): The answer; only for "drafted".
        citations (iterable[dict]): _citations() output.
        coverage (str): "high", "partial" or "none".
        missing_info (iterable[str]): _clip_missing() output.
        safety_flags (iterable[dict]): safety.flag() entries (checkpoint 2).
        model (str | None): The model that answered, None without a call.
        retrieved (iterable[dict]): {"entry_id", "title", "similarity"} for
            the passages sent, or the ones checked at the gate.

    Returns:
        dict: {"status", "reason", "draft", "knowledge_coverage",
        "missing_info", "safety_flags", "model", "prompt_version",
        "retrieved"}, where draft is {"ai_text", "citations",
        "used_web_search": False} when drafted, otherwise None.

    Side effects: none.
    """
    draft_ = None if ai_text is None else {"ai_text": ai_text, "citations": list(citations), "used_web_search": False}
    return {"status": status, "reason": reason, "draft": draft_, "knowledge_coverage": coverage,
            "missing_info": list(missing_info), "safety_flags": list(safety_flags), "model": model,
            "prompt_version": prompt_version(profile, DRAFT_VERSION), "retrieved": list(retrieved)}


def _log(decision, started, usage, best):
    """Log one line about the decision and pass it through.

    Only metadata is logged: no question, passage, answer or missing_info
    text, and no keys.

    Args:
        decision (dict): The decision about to be returned.
        started (float): time.monotonic() when draft() began.
        usage (dict): _write's usage dict.
        best (float | None): The best similarity, or None without a search.

    Returns:
        dict: The same decision, unchanged.

    Side effects: one INFO log line.
    """
    metas = usage["metas"]
    logger.info("Draft stage=draft status=%s reason=%s coverage=%s passages=%d best_similarity=%s flags=%d "
                "attempts=%d attempt=%s invalid=%s latency_ms=%d prompt_tokens=%d completion_tokens=%d cost=%.6f",
                decision["status"], decision["reason"] or "none", decision["knowledge_coverage"],
                len(decision["retrieved"]), "none" if best is None else f"{best:.3f}",
                len(decision["safety_flags"]), usage["attempts"], metas[-1]["attempt"] if metas else "none",
                ",".join(usage["codes"]) or "none", int((time.monotonic() - started) * 1000),
                sum(meta.get("prompt_tokens") or 0 for meta in metas),
                sum(meta.get("completion_tokens") or 0 for meta in metas),
                sum(meta.get("cost") or 0 for meta in metas))
    return decision


def draft(question_text, *, creator_id, rounds=None, original_text=None, channel="instagram",
          safety_flagged=False, flagged_topics=None, profile=None, search=None, time_left=None):
    """Draft a grounded answer for one paid question.

    Steps (spec 6.5, 14.3, 14.7): blank question -> no_draft; search query =
    question plus non-empty replies (first QUERY_MAX_CHARS characters);
    retrieve SEARCH_K guide chunks; best similarity below
    DRAFT_MIN_SIMILARITY -> no_draft with no model call; write with one
    retry on invalid output; coverage "none" -> no_draft; checkpoint 2 on
    the answer (a severe category or blocked term drops the text); citations.

    Args:
        question_text (str | None): questions.question_text.
        creator_id (str): questions.creator_id.
        rounds (list[dict] | None): clarification_rounds rows
            [{"round", "prompt", "reply"}] for the origin message, any order.
        original_text (str | None): The origin inbound message's text; shown
            to the model only when it differs from the question.
        channel (str): questions.source, "instagram" or "knowledge_app";
            sets the length limit.
        safety_flagged (bool): questions.safety_flagged; adds a risk note.
        flagged_topics (list[str] | None): The detail values of the origin
            message's checkpoint-1 policy/risk_topic flags. Values outside the
            profile's risk_topics are dropped, so DM text can never reach the
            prompt this way.
        profile (dict | None): prompts.profile_for(creator_id); defaults to
            SWEETLIFE_FLORA.
        search (callable | None): Same contract as knowledge.search; None
            means knowledge.search, looked up at call time.
        time_left (float | None): Seconds left in the Lambda. None means no
            limit (eval and local runs); otherwise the deadline passed to
            llm.write_draft is _clock() + time_left.

    Returns:
        dict: The decision (see _decision for the shape):
            drafted                      the answer, citations and coverage
            no_draft / empty_question    blank question, no calls
            no_draft / no_coverage       below the gate (missing_info [] and
                                         model None), or the model said
                                         coverage "none" (its missing_info)
            no_draft / invalid_output    invalid twice, or no time to retry
            no_draft / safety_blocked    checkpoint 2 blocked; text dropped,
                                         flags and the model's coverage kept
        Coverage is "none" for empty, gate and invalid output.

    Raises:
        ValueError: If the profile has no byte limit for the channel.
        llm.LLMError: If OpenAI, OpenRouter or Supabase fails, including
            ("openrouter", None, "deadline") when the first model call cannot
            start in time. The worker resets the question and retries.
        RuntimeError: If a key or Supabase setting is missing.

    Side effects: one search (an embedding and an RPC), up to two draft
    calls, one moderation call and one log line. No database writes.
    """
    started = time.monotonic()
    profile = profile or SWEETLIFE_FLORA
    answer_char_target(profile, channel)  # an unknown channel raises before any call
    deadline = None if time_left is None else _clock() + time_left
    usage = {"attempts": 0, "metas": [], "codes": []}
    question = question_text.strip() if isinstance(question_text, str) else ""
    if not question:
        return _log(_decision("no_draft", profile, reason="empty_question"), started, usage, None)
    rounds = _rounds(rounds)
    topics = list(dict.fromkeys(topic for topic in flagged_topics or [] if topic in profile["risk_topics"]))
    query = "\n".join([question, *(item["reply"] for item in rounds if item["reply"])])[:QUERY_MAX_CHARS]
    results = (search or knowledge.search)(query, creator_id, k=SEARCH_K, sources=list(SEARCH_SOURCES))
    retrieved = [{"entry_id": r["entry_id"], "title": r["title"], "similarity": r["similarity"]} for r in results]
    best = max((r["similarity"] for r in results), default=0.0)
    if best < DRAFT_MIN_SIMILARITY:
        return _log(_decision("no_draft", profile, reason="no_coverage", retrieved=retrieved), started, usage, best)
    passages = [(f"K{i}", result) for i, result in enumerate(results, 1)]
    refs = [ref for ref, _ in passages]
    original = original_text.strip() if isinstance(original_text, str) else ""
    user = _user_message(question, original if original != question else "", rounds,
                         _note(safety_flagged, topics), passages)
    data = _write(draft_prompt(profile, channel), user, _schema(refs, profile), refs, profile, channel,
                  deadline, usage)
    model = usage["metas"][-1]["model"] if usage["metas"] else None
    if data is None:
        return _log(_decision("no_draft", profile, reason="invalid_output", model=model, retrieved=retrieved),
                    started, usage, best)
    coverage, missing_info = data["knowledge_coverage"], _clip_missing(data["missing_info"])
    if coverage == "none":
        return _log(_decision("no_draft", profile, reason="no_coverage", missing_info=missing_info, model=model,
                              retrieved=retrieved), started, usage, best)
    answer = data["answer"].strip()
    # Checkpoint 2. llm.moderate is looked up here, at call time, so a test
    # that replaces draft.llm with a fake also replaces the moderation call.
    screened = safety.screen(answer, profile, moderate=llm.moderate)
    flags = screened["flags"] + [safety.flag("policy", "risk_topic", topic)
                                 for topic in dict.fromkeys(data["risk_topics"])]
    if screened["severe"] or screened["blocked_term"]:
        return _log(_decision("no_draft", profile, reason="safety_blocked", coverage=coverage,
                              missing_info=missing_info, safety_flags=flags, model=model, retrieved=retrieved),
                    started, usage, best)
    return _log(_decision("drafted", profile, ai_text=answer, citations=_citations(data["used_sources"], passages),
                          coverage=coverage, missing_info=missing_info, safety_flags=flags, model=model,
                          retrieved=retrieved), started, usage, best)
