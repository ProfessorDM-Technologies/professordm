import logging
import re
import time

import llm
from prompts import CLARIFY_VERSION, SWEETLIFE_FLORA, TRIAGE_VERSION, prompt_version


CONFIDENCE_CUTOFF = 0.6
MILD_FLAG_THRESHOLD = 0.5
SEVERE_FLAG_THRESHOLD = 0.5
MAX_ROUNDS = 2
SEVERE = {
    "self-harm/intent",
    "self-harm/instructions",
    "sexual/minors",
    "harassment/threatening",
    "hate/threatening",
}
SCORED_SEVERE = {"harassment/threatening", "hate/threatening"}
BLOCKED_TERMS = (
    "kill yourself",
    "kys",
    "send nudes",
    "child porn",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _flag(layer, category, detail=None):
    return {"layer": layer, "category": category, "detail": detail}


def _decision(status, profile, *, category=None, service_kind=None, confidence=None, reason=None,
              model=None, safety_flags=(), question=None, clarification=None, outbound=None,
              version=TRIAGE_VERSION):
    return {"status": status, "category": category, "service_kind": service_kind,
            "confidence": confidence, "reason": reason,
            "prompt_version": prompt_version(profile, version), "model": model,
            "safety_flags": list(safety_flags), "question": question,
            "clarification": clarification, "outbound": outbound}


def _clarifying(profile, round_, prompt, version=TRIAGE_VERSION, **fields):
    return _decision("awaiting_clarification", profile, clarification={"round": round_, "prompt": prompt},
                     outbound={"type": "clarification", "text": prompt}, version=version, **fields)


def _blocked(profile, flags, reason, model=None, text_key="decline_text"):
    return _decision("blocked", profile, category="safety_concern", reason=reason, model=model,
                     safety_flags=flags, outbound={"type": "decline", "text": profile[text_key]})


def _blocked_term(text, profile):
    terms = [*BLOCKED_TERMS, *profile.get("extra_blocked_terms", [])]
    pattern = "|".join(re.escape(term.strip()).replace(r"\ ", r"\s+") for term in terms if term.strip())
    return bool(pattern) and re.search(rf"(?<!\w)(?:{pattern})(?!\w)", text, re.IGNORECASE) is not None


def _screen(text, profile):
    hits = llm.moderate(text)
    severe = [category for category, score in hits.items() if category in SEVERE
              and (category not in SCORED_SEVERE or score >= SEVERE_FLAG_THRESHOLD)]
    flags = [_flag("moderation", category) for category, score in hits.items()
             if category in severe or score >= MILD_FLAG_THRESHOLD]
    if severe:
        crisis = any(category.startswith("self-harm") for category in severe)
        return _blocked(profile, flags, f"Moderation flagged {', '.join(severe)}", llm.MODERATION_MODEL,
                        "crisis_text" if crisis else "decline_text"), flags
    if _blocked_term(text, profile):
        return _blocked(profile, [*flags, _flag("rules", "blocked_term")], "Matched a blocked term"), flags
    return None, flags


def _classify(text, recent_messages, profile, rounds=None):
    for _ in range(2):
        try:
            return llm.classify(text, recent_messages, profile, rounds)
        except llm.InvalidOutput:
            continue
    return None


def _clarification(text, recent_messages, profile, rounds=None):
    for _ in range(2):
        try:
            return llm.write_clarification(text, recent_messages, profile, rounds)
        except llm.InvalidOutput:
            continue
    return None


def _route(result, profile, flags, question_text, next_round, clarify):
    category = result["category"]
    flags = list(flags)
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
    confidence = decision["confidence"]
    logger.info("Triage stage=%s status=%s category=%s confidence=%s flags=%d latency_ms=%d",
                stage, decision["status"], decision["category"],
                "none" if confidence is None else f"{confidence:.2f}",
                len(decision["safety_flags"]), int((time.monotonic() - started) * 1000))
    return decision


def _recent(recent_messages):
    return [m.strip() for m in recent_messages or [] if isinstance(m, str) and m.strip()]


def _invalid(profile, flags):
    return _decision("creator_decision", profile, model=llm.model_id(), safety_flags=flags,
                     reason="Model returned invalid output twice")


def triage(text, recent_messages=None, profile=None):
    started = time.monotonic()
    profile = profile or SWEETLIFE_FLORA
    recent_messages = _recent(recent_messages)
    if not isinstance(text, str) or not text.strip():
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
