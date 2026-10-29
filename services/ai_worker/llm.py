"""Model calls for triage: moderation, classification and clarification text.

This is the only file in ai_worker that makes HTTP calls. Keeping every
network call here lets triage.py stay pure decision logic, and lets the tests
swap this whole module for a fake.

Services:
    OpenAI moderation (omni-moderation-latest)  safety layer 1, free
    OpenRouter chat completions (TRIAGE_MODEL)  classification and the
                                                clarification question

Depends on:
    The standard library only (urllib, json, re, time, os, logging), matching
    services/instagram_backend, so the Lambda needs no packaging.
    prompts for the templates, categories and service kinds.
    Environment variables OPENAI_API_KEY, OPENROUTER_API_KEY and optionally
    TRIAGE_MODEL, read at call time, never at import, so tests and Lambda
    configuration can set them late.

Never does:
    - Decide routing or statuses (that is triage.py).
    - Touch the database or Instagram.
    - Log DM text, model output text or keys. Logs carry stage, category,
      confidence, flagged category names, character counts, latency and error
      types only.
    - Retry network errors. An LLMError goes up to the backend, which resets
      the message status and retries later.
"""

import json
import logging
import os
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from prompts import CATEGORIES, SERVICE_KINDS, clarify_prompt, triage_prompt


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODERATION_URL = "https://api.openai.com/v1/moderations"

# The classifier used when TRIAGE_MODEL is not set. Gemini 3.1 Flash-Lite is the
# model in the tech matrix. On eval it passed all three bars (98.0% test
# accuracy, 100% safety_concern recall) and beat 3.5 Flash-Lite, which missed a
# pet emergency on the test split.
DEFAULT_MODEL = "google/gemini-3.1-flash-lite"

# OpenAI's current moderation model (confirmed available to our key in October
# 2026). "latest" follows OpenAI's updates, so moderation scores can shift over
# time; re-run eval if blocks or flags change unexpectedly.
MODERATION_MODEL = "omni-moderation-latest"

# Clarification DMs must be shorter than this. 200 characters is about two
# short questions: enough to ask for the missing details, short enough to read
# on a phone and well under Instagram's 1000-byte message limit.
MAX_CLARIFICATION_CHARS = 200

# A clarification that mentions media is rejected. Triage only reads text
# (there is no image upload yet), so asking for a photo would invite something
# we cannot see. Mentioning one ("I can't see photos") also confused followers,
# so the prompt forbids both and this check enforces it.
MEDIA_WORDS = re.compile(r"\b(photos?|pics?|pictures?|images?|videos?|screenshots?)\b", re.IGNORECASE)

# Seconds per model call. Keeps one slow provider from holding the Lambda;
# typical calls take 0.3 to 2 seconds.
TIMEOUT = 10

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class LLMError(Exception):
    """A model API call failed (HTTP error, timeout, network or bad response).

    Raised instead of returning a fallback decision, so a temporary outage is
    never stored as a real triage result. The backend catches it, resets the
    message status and retries later.

    Attributes:
        service (str): "openai" or "openrouter".
        status (int | None): The HTTP status, or None for network errors.
        code (str | int | None): The provider's error code or type when it
            sent one, or the Python exception name for network errors. Safe to
            log: it never contains DM text.
    """

    def __init__(self, service, status=None, code=None):
        """Store the error details and build a short, loggable message.

        Args:
            service (str): "openai" or "openrouter".
            status (int | None): HTTP status, if any.
            code (str | int | None): Provider error code or exception name.

        Side effects: none.
        """
        super().__init__(f"{service} request failed ({status or 'network'}, {code or 'unknown'})")
        self.service = service
        self.status = status
        self.code = code


class InvalidOutput(Exception):
    """The model answered, but the answer broke the contract.

    For example: not JSON, an unknown category, confidence outside 0 to 1, or
    a clarification that is too long or mentions photos. triage.py retries
    once, then hands the message to the creator. The message (args[0]) is a
    short code such as "bad_category", never model text.
    """


def _key(variable):
    """Read an API key from the environment at call time.

    Args:
        variable (str): The environment variable name.

    Returns:
        str: The key.

    Raises:
        RuntimeError: If the variable is missing or empty. The message names
            the variable, never a value.

    Side effects: none.
    """
    value = os.environ.get(variable)
    if not value:
        raise RuntimeError(f"Missing {variable}")
    return value


def _json_request(service, url, headers, body, timeout=TIMEOUT):
    """POST a JSON body and return the parsed JSON response.

    Same pattern as services/instagram_backend/clients._json_request, with
    every failure turned into LLMError so callers handle one exception type.

    Args:
        service (str): "openai" or "openrouter", recorded on errors.
        url (str): The endpoint.
        headers (dict[str, str]): Request headers, including Authorization.
        body (dict): The JSON body.
        timeout (float): Seconds before giving up.

    Returns:
        Any: The parsed JSON response (normally a dict).

    Raises:
        LLMError: On an HTTP error (with the status and the provider's error
            code or type), a timeout, a network error or a non-JSON response.

    Side effects: one HTTPS request.
    """
    request = Request(url, data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
                      headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as error:
        # Keep only the provider's error code or type. The message text can
        # echo request content, so it is dropped.
        try:
            detail = json.loads(error.read())
            inner = detail.get("error") if isinstance(detail, dict) else None
            code = inner.get("code") or inner.get("type") if isinstance(inner, dict) else None
        except (ValueError, AttributeError):
            code = None
        raise LLMError(service, error.code, code) from None
    except (OSError, ValueError) as error:
        # OSError covers URLError, timeouts and dropped connections; ValueError
        # covers a response body that is not JSON.
        raise LLMError(service, None, type(error).__name__) from None


def model_id():
    """Return the classifier model id.

    Returns:
        str: TRIAGE_MODEL from the environment, or DEFAULT_MODEL.

    Side effects: none.
    """
    return os.environ.get("TRIAGE_MODEL") or DEFAULT_MODEL


def _openrouter(system, user, schema=None):
    """Call OpenRouter chat completions once.

    Temperature is 0 so the same DM gets the same answer as far as the
    provider allows. With a schema, the response is forced into strict JSON,
    and require_parameters makes OpenRouter refuse providers that would
    silently ignore the schema.

    Args:
        system (str): The system prompt.
        user (str): The user message (the rendered conversation).
        schema (dict | None): A JSON schema for structured output, or None
            for plain text.

    Returns:
        tuple[str | None, dict]: (content, meta). content is the model's reply
        text. meta is {"model": str, "latency_ms": int, "prompt_tokens": int,
        "completion_tokens": int, "cost": float | None}.

    Raises:
        LLMError: On any API failure, or a response with an error or no choices.
        RuntimeError: If OPENROUTER_API_KEY is missing.

    Side effects: one HTTPS request.
    """
    model = model_id()
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "usage": {"include": True}}
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "triage", "strict": True, "schema": schema}}
        body["provider"] = {"require_parameters": True}
    started = time.monotonic()
    response = _json_request("openrouter", OPENROUTER_URL,
                             {"Authorization": f"Bearer {_key('OPENROUTER_API_KEY')}",
                              "Content-Type": "application/json"}, body)
    latency_ms = int((time.monotonic() - started) * 1000)
    if not isinstance(response, dict) or response.get("error") or not response.get("choices"):
        error = response.get("error") if isinstance(response, dict) else None
        raise LLMError("openrouter", None, error.get("code") if isinstance(error, dict) else "no_choices")
    content = (response["choices"][0].get("message") or {}).get("content")
    usage = response.get("usage") or {}
    return content, {"model": response.get("model") or model, "latency_ms": latency_ms,
                     "prompt_tokens": usage.get("prompt_tokens", 0),
                     "completion_tokens": usage.get("completion_tokens", 0),
                     "cost": usage.get("cost")}


def _conversation(text, recent_messages, rounds=None):
    """Render the DM and its context as the user message for the model.

    Every DM is JSON-quoted so the model sees exactly where follower text
    starts and ends. That makes instructions hidden inside a DM easier to
    treat as data (the prompts also say so).

    Args:
        text (str): The latest DM, or the original message when rounds are given.
        recent_messages (list[str]): Earlier DMs from the same follower, oldest first.
        rounds (list[dict] | None): Clarification rounds
            [{"round": int, "prompt": str, "reply": str}].

    Returns:
        str: Lines like:
            Earlier messages, oldest first:
            1. "hi"
            Latest message:           (or "Original message:" with rounds)
            "why are the tips brown"
            Clarification so far:     (only with rounds)
            Round 1 question from the creator: "..."
            Round 1 reply from the follower: "..."

    Side effects: none.
    """
    lines = []
    if recent_messages:
        lines.append("Earlier messages, oldest first:")
        lines += [f"{i}. {json.dumps(m, ensure_ascii=False)}" for i, m in enumerate(recent_messages, 1)]
    lines.append("Original message:" if rounds else "Latest message:")
    lines.append(json.dumps(text, ensure_ascii=False))
    if rounds:
        lines.append("Clarification so far:")
        for item in rounds:
            lines.append(f"Round {item['round']} question from the creator: "
                         f"{json.dumps(item.get('prompt') or '', ensure_ascii=False)}")
            lines.append(f"Round {item['round']} reply from the follower: "
                         f"{json.dumps(item.get('reply') or '', ensure_ascii=False)}")
    return "\n".join(lines)


def _classify_schema(profile):
    """Build the strict JSON schema for one classification.

    The schema is built per profile because risk_reason is an enum of that
    creator's risk topics. Limiting it to fixed tags means a safety flag's
    detail can never contain DM text or a model paraphrase of it.

    Args:
        profile (dict): The creator profile (uses profile["risk_topics"]).

    Returns:
        dict: A JSON schema object requiring category (one of the 6),
        service_kind ("" or platform | business | out_of_domain),
        confidence (number), reason (string), risk_flag (boolean) and
        risk_reason ("" or one of the profile's risk topics).

    Side effects: none.
    """
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "service_kind": {"type": "string", "enum": ["", *SERVICE_KINDS]},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
            "risk_flag": {"type": "boolean"},
            "risk_reason": {"type": "string", "enum": ["", *profile["risk_topics"]]},
        },
        "required": ["category", "service_kind", "confidence", "reason", "risk_flag", "risk_reason"],
        "additionalProperties": False,
    }


def _parse_classification(content, profile):
    """Validate the model's JSON and normalize it.

    The strict schema should already guarantee most of this, but providers
    occasionally ignore it, so every rule is checked again here.

    Args:
        content (str | None): The raw model reply.
        profile (dict): The creator profile (for the allowed risk topics).

    Returns:
        dict: {"category": str, "service_kind": str | None,
        "confidence": float, "reason": str, "risk_flag": bool,
        "risk_reason": str | None}. service_kind is set only for
        service_request; risk_reason only when risk_flag is True.

    Raises:
        InvalidOutput: With code not_json, bad_category, bad_confidence,
            bad_fields, bad_service_kind or bad_risk_reason.

    Side effects: none.
    """
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        raise InvalidOutput("not_json") from None
    if not isinstance(data, dict) or data.get("category") not in CATEGORIES:
        raise InvalidOutput("bad_category")
    confidence = data.get("confidence")
    # bool is a subclass of int in Python, so True would otherwise pass as 1.
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise InvalidOutput("bad_confidence")
    if not isinstance(data.get("reason"), str) or not isinstance(data.get("risk_flag"), bool):
        raise InvalidOutput("bad_fields")
    service_kind = None
    if data["category"] == "service_request":
        service_kind = data.get("service_kind")
        if service_kind not in SERVICE_KINDS:
            raise InvalidOutput("bad_service_kind")
    risk_reason = data.get("risk_reason") if data["risk_flag"] else None
    if data["risk_flag"] and risk_reason not in profile["risk_topics"]:
        raise InvalidOutput("bad_risk_reason")
    return {"category": data["category"], "service_kind": service_kind,
            "confidence": float(confidence), "reason": data["reason"].strip(),
            "risk_flag": data["risk_flag"], "risk_reason": risk_reason}


def classify(text, recent_messages, profile, rounds=None):
    """Classify one DM (or a clarification exchange) into one of 6 categories.

    Safety layer 3 (the policy check) is part of this call: risk_flag marks a
    profile risk topic, so it does not need a separate model call.

    Args:
        text (str): The DM text, or the original message for reassess.
        recent_messages (list[str]): Earlier DMs from the same follower, oldest first.
        profile (dict): The creator profile that fills the generic template.
        rounds (list[dict] | None): Clarification rounds for reassess.

    Returns:
        dict: {"category", "service_kind", "confidence", "reason",
        "risk_flag", "risk_reason"} from _parse_classification, plus "model",
        "latency_ms", "prompt_tokens", "completion_tokens" and "cost" from
        the API call.

    Raises:
        InvalidOutput: If the reply breaks the contract (logged as a warning
            with the error code only).
        LLMError: On an API failure.
        RuntimeError: If OPENROUTER_API_KEY is missing.

    Side effects: one OpenRouter call and one log line.
    """
    content, meta = _openrouter(triage_prompt(profile), _conversation(text, recent_messages, rounds),
                                _classify_schema(profile))
    try:
        result = _parse_classification(content, profile)
    except InvalidOutput as error:
        logger.warning("Triage stage=classify FAIL error_type=invalid_output detail=%s latency_ms=%d",
                       error, meta["latency_ms"])
        raise
    logger.info("Triage stage=classify PASS category=%s confidence=%.2f latency_ms=%d",
                result["category"], result["confidence"], meta["latency_ms"])
    return {**result, **meta}


def moderate(text):
    """Run OpenAI moderation on one DM (safety layer 1).

    Args:
        text (str): The DM text.

    Returns:
        dict[str, float]: Only the categories OpenAI flagged, each mapped to
        its score, for example {"harassment": 0.89, "violence": 0.13}. Empty
        when nothing was flagged. triage.py decides what blocks and what is
        only a flag.

    Raises:
        LLMError: On an API failure, or a response without categories and
            scores.
        RuntimeError: If OPENAI_API_KEY is missing.

    Side effects: one OpenAI call and one log line listing flagged category
    names (never text).
    """
    started = time.monotonic()
    response = _json_request("openai", MODERATION_URL,
                             {"Authorization": f"Bearer {_key('OPENAI_API_KEY')}",
                              "Content-Type": "application/json"},
                             {"model": MODERATION_MODEL, "input": text})
    results = response.get("results") if isinstance(response, dict) else None
    result = results[0] if isinstance(results, list) and results and isinstance(results[0], dict) else {}
    categories, scores = result.get("categories"), result.get("category_scores")
    if not isinstance(categories, dict) or not isinstance(scores, dict):
        # An unreadable moderation response is treated as an outage, never as
        # "nothing flagged", so an unscreened message cannot slip through.
        raise LLMError("openai", None, "bad_response")
    flagged = {name: float(scores.get(name) or 0) for name, hit in sorted(categories.items()) if hit is True}
    logger.info("Triage stage=moderation PASS flagged=%s latency_ms=%d",
                ",".join(flagged) or "none", int((time.monotonic() - started) * 1000))
    return flagged


def write_clarification(text, recent_messages, profile, rounds=None):
    """Write a short clarification DM asking for the missing details.

    Args:
        text (str): The vague DM, or the original message for reassess.
        recent_messages (list[str]): Earlier DMs from the same follower.
        profile (dict): The creator profile (domain, clear_question_needs, voice).
        rounds (list[dict] | None): Rounds already asked, so the next question
            does not repeat one.

    Returns:
        str: The clarification text, stripped. It is non-empty, shorter than
        MAX_CLARIFICATION_CHARS and never mentions media.

    Raises:
        InvalidOutput: If the text is empty, too long or mentions photos,
            videos or screenshots (logged with the character count only).
        LLMError: On an API failure.
        RuntimeError: If OPENROUTER_API_KEY is missing.

    Side effects: one OpenRouter call and one log line.
    """
    content, meta = _openrouter(clarify_prompt(profile), _conversation(text, recent_messages, rounds))
    prompt = content.strip() if isinstance(content, str) else ""
    if not prompt or len(prompt) >= MAX_CLARIFICATION_CHARS or MEDIA_WORDS.search(prompt):
        logger.warning("Triage stage=clarify FAIL error_type=invalid_output chars=%d latency_ms=%d",
                       len(prompt), meta["latency_ms"])
        raise InvalidOutput("bad_clarification")
    logger.info("Triage stage=clarify PASS chars=%d latency_ms=%d", len(prompt), meta["latency_ms"])
    return prompt
