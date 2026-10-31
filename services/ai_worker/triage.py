"""Triage decisions for inbound Instagram DMs.

This module turns one DM (plus a little context) into a single decision dict
that says what should happen next: which inbound status to set, whether to
create a paid question, whether to ask a clarifying question, whether to send a
decline, and which safety flags to record.

Entry points:
    triage(text, recent_messages=None, profile=None)
        For a new DM that is not a reply to an open clarification.
    reassess(original_text, rounds, recent_messages=None, profile=None)
        For a follower's reply to a clarification question.

Depends on:
    llm      for every model call (moderation, classification, clarification
             text). Tests replace this module with a fake.
    safety   for safety layers 1 and 2 (moderation thresholds, blocked terms),
             shared with draft. Its names are re-exported here, so
             triage.SEVERE, triage._flag and the rest keep working.
    prompts  for the default creator profile and the prompt version strings.

Never does:
    - Make HTTP calls itself. All network access goes through `llm`, so the
      decision logic can be tested without a network.
    - Read or write the database, send DMs, or touch Instagram. The backend
      (services/instagram_backend) loads the data, calls these functions and
      writes the returned decision to the tables. See README.md for the mapping.
    - Log DM text or API keys. Logs carry only stage, status, category,
      confidence, flag count and latency.
"""

import logging
import time

import llm
import safety
from prompts import CLARIFY_VERSION, SWEETLIFE_FLORA, TRIAGE_VERSION, prompt_version
# Re-exported so existing callers (tests, eval_triage.py) can still read them
# from triage. The values and their reasoning live in safety.py.
from safety import (BLOCKED_TERMS, MILD_FLAG_THRESHOLD, SCORED_SEVERE, SEVERE, SEVERE_FLAG_THRESHOLD,
                    blocked_term, flag)

_flag = flag
_blocked_term = blocked_term


# Below this classifier confidence, the creator decides instead of the router.
# 0.6 is the starting value from the design. On both the dev and the synthetic
# test split every prediction scored 0.90 to 1.0, including the wrong ones, so
# no cutoff caught an error without also losing right answers. It stays at 0.6
# until real DMs show where confidence and accuracy diverge.
CONFIDENCE_CUTOFF = 0.6

# Maximum clarification questions per message. Two rounds give the follower a
# fair chance to add the missing details without turning the DM into an
# interview; after that a human (the creator) is better placed to decide.
# Matches the clarification_rounds.round check (1 to 2) in the schema.
MAX_ROUNDS = 2

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _decision(status, profile, *, category=None, service_kind=None, confidence=None, reason=None,
              model=None, safety_flags=(), question=None, clarification=None, outbound=None,
              version=TRIAGE_VERSION):
    """Assemble the decision dict that both entry points return.

    Every decision has the same keys so the backend never has to check for a
    missing field. Fields that do not apply are None or [].

    Args:
        status (str): The inbound status to set. One of ready_for_question,
            awaiting_clarification, closed_no_action, service_routed, blocked,
            creator_decision.
        profile (dict): The creator profile, used for the prompt version.
        category (str | None): One of the 6 MESSAGE_CATEGORIES, or None when
            the model failed.
        service_kind (str | None): platform, business or out_of_domain for a
            service_request, otherwise None.
        confidence (float | None): The classifier's confidence (0 to 1), or
            None when no model decided.
        reason (str | None): One human-readable sentence explaining the label.
        model (str | None): The model id that made the decision.
        safety_flags (iterable[dict]): Entries built by _flag.
        question (dict | None): {"question_text": str, "safety_flagged": bool}.
        clarification (dict | None): {"round": int, "prompt": str}.
        outbound (dict | None): {"type": "clarification" | "decline", "text": str}.
        version (str): The template version part of prompt_version, for
            example "triage-v4" or "triage-v4+clarify-v4".

    Returns:
        dict: {"status", "category", "service_kind", "confidence", "reason",
        "prompt_version", "model", "safety_flags", "question",
        "clarification", "outbound"}

    Side effects: none.
    """
    return {"status": status, "category": category, "service_kind": service_kind,
            "confidence": confidence, "reason": reason,
            "prompt_version": prompt_version(profile, version), "model": model,
            "safety_flags": list(safety_flags), "question": question,
            "clarification": clarification, "outbound": outbound}


def _clarifying(profile, round_, prompt, version=TRIAGE_VERSION, **fields):
    """Build an awaiting_clarification decision that asks the follower a question.

    The same text goes into `clarification` (stored as a clarification_rounds
    row) and `outbound` (sent as a DM), so what the thread shows matches what
    was sent.

    Args:
        profile (dict): The creator profile.
        round_ (int): The clarification round being asked, 1 or 2.
        prompt (str): The clarification text to send.
        version (str): Template version for prompt_version (includes the
            clarify version when the model wrote the text).
        **fields: Any other _decision fields (category, confidence, reason...).

    Returns:
        dict: A decision with status "awaiting_clarification".

    Side effects: none.
    """
    return _decision("awaiting_clarification", profile, clarification={"round": round_, "prompt": prompt},
                     outbound={"type": "clarification", "text": prompt}, version=version, **fields)


def _blocked(profile, flags, reason, model=None, text_key="decline_text"):
    """Build a blocked decision with a decline DM.

    Args:
        profile (dict): The creator profile, which holds the reply texts.
        flags (list[dict]): The safety flags explaining the block.
        reason (str): Why it was blocked, for example "Moderation flagged
            sexual/minors". Never contains DM text.
        model (str | None): The moderation model id, or None for a blocked term.
        text_key (str): Which profile text to send: "decline_text" normally,
            "crisis_text" for self-harm so the follower gets crisis resources
            rather than a cold refusal.

    Returns:
        dict: A decision with status "blocked", category "safety_concern" and
        an outbound of type "decline".

    Side effects: none.
    """
    return _decision("blocked", profile, category="safety_concern", reason=reason, model=model,
                     safety_flags=flags, outbound={"type": "decline", "text": profile[text_key]})


def _screen(text, profile):
    """Run safety layers 1 (moderation) and 2 (blocked terms) on one DM.

    A thin wrapper around safety.screen: a severe moderation hit blocks first
    (layer 1), then a blocked term (layer 2). Everything else is returned as
    flags and the message continues to classification.

    Args:
        text (str): The DM text to screen (a new DM, or the newest reply).
        profile (dict): The creator profile.

    Returns:
        tuple[dict | None, list[dict]]: (blocked_decision, flags).
        blocked_decision is a "blocked" decision when the message must stop
        here, otherwise None. flags are the moderation flags to carry forward
        (callers only use them when nothing blocked).

    Raises:
        llm.LLMError: If the moderation call fails. Not caught here, so the
            backend can retry later instead of letting an unscreened message
            through.

    Side effects: one moderation API call (through llm), logged without text.
    """
    # llm.moderate is looked up here, at call time, so a test that replaces
    # triage.llm with a fake also replaces the moderation call.
    screened = safety.screen(text, profile, moderate=llm.moderate)
    flags = screened["flags"]
    if screened["severe"]:
        # Someone in crisis gets crisis resources (988), not a generic decline.
        return _blocked(profile, flags, f"Moderation flagged {', '.join(screened['severe'])}", llm.MODERATION_MODEL,
                        "crisis_text" if screened["crisis"] else "decline_text"), flags
    if screened["blocked_term"]:
        return _blocked(profile, flags, "Matched a blocked term"), flags
    return None, flags


def _classify(text, recent_messages, profile, rounds=None):
    """Classify with one retry on invalid model output.

    Args:
        text (str): The DM text (or the original message for reassess).
        recent_messages (list[str]): Earlier DMs from the same follower,
            oldest first.
        profile (dict): The creator profile.
        rounds (list[dict] | None): Clarification rounds for reassess.

    Returns:
        dict | None: The llm.classify result ({"category", "service_kind",
        "confidence", "reason", "risk_flag", "risk_reason", "model",
        "latency_ms", "prompt_tokens", "completion_tokens", "cost"}), or None
        if the model returned invalid output twice.

    Raises:
        llm.LLMError: On a network or API error. Retrying an outage here would
            only add latency; the backend retries the whole message later.

    Side effects: one or two classification API calls.
    """
    # Invalid output (bad JSON, unknown category, confidence out of range) is
    # usually a one-off, so one retry is worth it. A second failure goes to the
    # creator rather than looping.
    for _ in range(2):
        try:
            return llm.classify(text, recent_messages, profile, rounds)
        except llm.InvalidOutput:
            continue
    return None


def _clarification(text, recent_messages, profile, rounds=None):
    """Write the clarification question, with one retry on invalid output.

    Args:
        text (str): The DM text (or the original message for reassess).
        recent_messages (list[str]): Earlier DMs from the same follower.
        profile (dict): The creator profile.
        rounds (list[dict] | None): Rounds already asked, so the model does not
            repeat a question.

    Returns:
        str | None: The clarification text, or None if the model failed twice
        (empty, 200 characters or more, or it mentioned photos or videos).

    Raises:
        llm.LLMError: On a network or API error.

    Side effects: one or two OpenRouter calls.
    """
    for _ in range(2):
        try:
            return llm.write_clarification(text, recent_messages, profile, rounds)
        except llm.InvalidOutput:
            continue
    return None


def _route(result, profile, flags, question_text, next_round, clarify):
    """Turn a classification result into the final decision (the routing table).

    Order matters: low confidence and safety_concern go to the creator before
    any automatic action, so nothing is sent or charged on a shaky or unsafe
    label.

    Args:
        result (dict): The llm.classify result.
        profile (dict): The creator profile.
        flags (list[dict]): Moderation flags from _screen.
        question_text (str): The text to put on a new question if this is
            ready_for_question (the DM joined with recent messages or replies).
        next_round (int): The clarification round that would be asked next
            (1 for triage, len(rounds) + 1 for reassess).
        clarify (callable[[], str | None]): Writes the clarification text.
            Passed as a function so the model is only called when the route
            actually needs a clarification.

    Returns:
        dict: The decision. Routing:
            confidence < CONFIDENCE_CUTOFF   -> creator_decision (keeps category)
            safety_concern                   -> creator_decision + policy flag
            expert_question                  -> ready_for_question + question
            needs_clarification              -> awaiting_clarification + clarification
                                                and outbound, or creator_decision
                                                after MAX_ROUNDS or if writing fails
            service_request                  -> service_routed
            social, spam_irrelevant          -> closed_no_action

    Raises:
        llm.LLMError: If writing the clarification hits a network or API error.

    Side effects: may call clarify(), which calls the model.
    """
    category = result["category"]
    flags = list(flags)
    # A risk topic never blocks or changes the status: the question can still be
    # answered, but the creator should review it. risk_reason is limited to the
    # profile's risk topics by the schema, so the flag detail never holds DM text.
    if result["risk_flag"]:
        flags.append(_flag("policy", "risk_topic", result["risk_reason"]))
    if category == "safety_concern":
        flags.append(_flag("policy", "safety_concern"))
    fields = {"category": category, "service_kind": result["service_kind"],
              "confidence": result["confidence"], "reason": result["reason"],
              "model": result["model"], "safety_flags": flags}
    if result["confidence"] < CONFIDENCE_CUTOFF or category == "safety_concern":
        return _decision("creator_decision", profile, **fields)
    if category == "expert_question":
        # Any flag (mild moderation or a risk topic) marks the question so the
        # creator reviews it in Moderation before answering.
        return _decision("ready_for_question", profile, **fields, question={
            "question_text": question_text, "safety_flagged": bool(flags)})
    if category == "needs_clarification":
        if next_round > MAX_ROUNDS:
            return _decision("creator_decision", profile, **{
                **fields, "reason": f"Still unclear after {MAX_ROUNDS} clarification rounds"})
        prompt = clarify()
        if prompt is None:
            return _decision("creator_decision", profile,
                             **{**fields, "reason": "Model failed to write a clarification twice"})
        return _clarifying(profile, next_round, prompt, version=f"{TRIAGE_VERSION}+{CLARIFY_VERSION}", **fields)
    if category == "service_request":
        return _decision("service_routed", profile, **fields)
    return _decision("closed_no_action", profile, **fields)


def _log(stage, decision, started):
    """Log one line about the decision and pass it through.

    Only metadata is logged: no DM text, no reason (it summarizes the DM) and
    no keys.

    Args:
        stage (str): "triage" or "reassess".
        decision (dict): The decision about to be returned.
        started (float): time.monotonic() when the call began.

    Returns:
        dict: The same decision, unchanged.

    Side effects: one INFO log line.
    """
    confidence = decision["confidence"]
    logger.info("Triage stage=%s status=%s category=%s confidence=%s flags=%d latency_ms=%d",
                stage, decision["status"], decision["category"],
                "none" if confidence is None else f"{confidence:.2f}",
                len(decision["safety_flags"]), int((time.monotonic() - started) * 1000))
    return decision


def _recent(recent_messages):
    """Clean the recent-messages context.

    Args:
        recent_messages (list | None): Earlier DMs from the same follower.

    Returns:
        list[str]: The non-empty strings, stripped, in their original order.

    Side effects: none.
    """
    return [m.strip() for m in recent_messages or [] if isinstance(m, str) and m.strip()]


def _invalid(profile, flags):
    """Build the decision for a model that returned invalid output twice.

    Args:
        profile (dict): The creator profile.
        flags (list[dict]): Moderation flags already found; kept so the
            creator still sees them.

    Returns:
        dict: A creator_decision with category None and a reason saying the
        model failed.

    Side effects: none.
    """
    return _decision("creator_decision", profile, model=llm.model_id(), safety_flags=flags,
                     reason="Model returned invalid output twice")


def triage(text, recent_messages=None, profile=None):
    """Decide what to do with a new DM.

    Steps: empty text -> ask for words (no model call); moderation (block on
    severe); blocked terms (block); classify with one retry; route.

    Args:
        text (str | None): The DM text. None or blank for a photo-only DM.
        recent_messages (list[str] | None): The same follower's other DMs from
            the 30 minutes before this one, oldest first, so a question split
            across several DMs is read as one. Only the latest message is
            moderated; earlier ones were screened when they arrived.
        profile (dict | None): The creator profile from prompts.profile_for().
            Defaults to SWEETLIFE_FLORA.

    Returns:
        dict: The decision (see _decision for the shape). For
        ready_for_question, question_text joins recent_messages and text with
        newlines.

    Raises:
        llm.LLMError: If OpenAI or OpenRouter fails (HTTP error, timeout,
            network). Raised instead of returning a decision so a temporary
            outage is never recorded as a real triage result; the backend
            resets the status and retries.
        RuntimeError: If an API key is missing from the environment.

    Side effects: up to 5 model calls (moderation, 2 classify, 2
    clarification) and one log line. No database or Instagram access.
    """
    started = time.monotonic()
    profile = profile or SWEETLIFE_FLORA
    recent_messages = _recent(recent_messages)
    if not isinstance(text, str) or not text.strip():
        # Only text DMs are handled; ask for the problem in words rather than
        # spending a model call on nothing.
        return _log("triage", _clarifying(profile, 1, profile["empty_text_prompt"], category="needs_clarification",
                                          reason="No text in the message, asks for a description in words"), started)
    text = text.strip()
    blocked, flags = _screen(text, profile)
    if blocked:
        return _log("triage", blocked, started)
    result = _classify(text, recent_messages, profile)
    if result is None:
        return _log("triage", _invalid(profile, flags), started)
    return _log("triage", _route(result, profile, flags, "\n".join([*recent_messages, text]), 1,
                                 lambda: _clarification(text, recent_messages, profile)), started)


def reassess(original_text, rounds, recent_messages=None, profile=None):
    """Decide again after the follower replied to a clarification question.

    Steps: screen the newest reply (moderation, blocked terms); classify the
    original message together with every round's question and reply; route.
    Still unclear after round 1 asks round 2; still unclear after round 2 goes
    to creator_decision.

    Args:
        original_text (str | None): The text of the message that is
            awaiting_clarification.
        rounds (list[dict]): Every clarification round for that message, with
            the new reply saved in the latest one:
            [{"round": 1, "prompt": str, "reply": str | None}, ...].
            Order does not matter; rounds are sorted by "round".
        recent_messages (list[str] | None): The follower's DMs from the 30
            minutes before the original message, oldest first.
        profile (dict | None): The creator profile. Defaults to SWEETLIFE_FLORA.

    Returns:
        dict: The decision for the original message (see _decision). For
        ready_for_question, question_text joins recent_messages, the original
        and every non-empty reply with newlines.

    Raises:
        ValueError: If rounds is empty or None; call triage() instead.
        llm.LLMError: If OpenAI or OpenRouter fails; the backend retries.
        RuntimeError: If an API key is missing.

    Side effects: up to 5 model calls and one log line.
    """
    started = time.monotonic()
    profile = profile or SWEETLIFE_FLORA
    recent_messages = _recent(recent_messages)
    if not rounds:
        raise ValueError("reassess needs at least one clarification round")
    original = original_text.strip() if isinstance(original_text, str) else ""
    rounds = [{"round": item["round"], "prompt": item.get("prompt") or "",
               "reply": item["reply"].strip() if isinstance(item.get("reply"), str) else ""}
              for item in sorted(rounds, key=lambda item: item["round"])]
    flags = []
    # Only the newest reply is new text; the original and earlier replies were
    # screened when they arrived. An empty reply has nothing to moderate.
    if rounds[-1]["reply"]:
        blocked, flags = _screen(rounds[-1]["reply"], profile)
        if blocked:
            return _log("reassess", blocked, started)
    result = _classify(original, recent_messages, profile, rounds)
    if result is None:
        return _log("reassess", _invalid(profile, flags), started)
    question_text = "\n".join(part for part in [*recent_messages, original, *(r["reply"] for r in rounds)] if part)
    return _log("reassess", _route(result, profile, flags, question_text, len(rounds) + 1,
                                   lambda: _clarification(original, recent_messages, profile, rounds)), started)
