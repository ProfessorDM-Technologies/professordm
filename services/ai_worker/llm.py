"""Model calls: moderation, classification, clarification text, drafts and embeddings.

This is the only file in ai_worker that makes HTTP calls. Keeping every
network call here lets triage.py stay pure decision logic, and lets the tests
swap this whole module for a fake.

Services:
    OpenAI moderation (omni-moderation-latest)  safety layer 1, free
    OpenRouter chat completions (TRIAGE_MODEL)  classification and the
                                                clarification question
    OpenRouter chat completions (DRAFT_MODEL,   the grounded answer draft,
        then DRAFT_FALLBACK_MODEL)              with a manual fallback
    OpenAI embeddings (text-embedding-3-small)  knowledge base vectors, for
                                                ingest and for query text

Every OpenRouter call sends provider {"data_collection": "deny"}, so only
providers that do not retain prompts are used (real DMs pass through).

Depends on:
    The standard library only (urllib, json, re, time, os, logging), matching
    services/instagram_backend, so the Lambda needs no packaging.
    prompts for the templates, categories and service kinds.
    Environment variables OPENAI_API_KEY, OPENROUTER_API_KEY and optionally
    TRIAGE_MODEL, DRAFT_MODEL and DRAFT_FALLBACK_MODEL, read at call time,
    never at import, so tests and Lambda configuration can set them late.

Never does:
    - Decide routing or statuses (that is triage.py), or validate draft
      fields (that is draft.py).
    - Touch the database or Instagram.
    - Log DM text, model output text, embedding input text or keys. Logs
      carry stage, category, confidence, flagged category names, character
      counts, batch and token counts, model ids, cost, latency and error
      types only.
    - Retry network errors at runtime. An LLMError goes up to the backend,
      which resets the message status and retries later. Two exceptions:
      embed(retry=True), which only the laptop ingest scripts use, and
      write_draft(), which tries a different model once when the primary
      has an outage.
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

EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"

# The embedding model for knowledge entries and query text (spec 6.1). Every
# stored vector and every query vector must come from this same model, or the
# similarity scores mean nothing; changing it means re-embedding every row.
EMBED_MODEL = "text-embedding-3-small"

# Vector length of EMBED_MODEL, and of knowledge_entries.embedding
# (vector(1536)). A vector of any other length would be rejected by the
# database or compare against the wrong space, so embed() checks every one.
EMBED_DIMENSIONS = 1536

# Inputs per embeddings request. OpenAI accepts up to 2048, but 100 chunks of
# up to about 800 tokens stay far below the per-request token limit, and a
# failed batch costs little to retry.
EMBED_BATCH = 100

# Seconds to wait before each retry of a failed embeddings batch when
# embed(retry=True): exponential, so a rate limit has time to clear. Five
# tries in total (the first plus one per wait), about 15 s at most.
EMBED_BACKOFF = (1, 2, 4, 8)

# The sleep used between embed retries. Module-level so tests can replace it
# and run without waiting.
_sleep = time.sleep

# Sent on every OpenRouter call (spec section 0, rule 6). OpenRouter then
# routes only to providers that do not store or train on prompts. Step 0
# (eval/check_providers.py) confirmed every model we use still finds one.
DATA_COLLECTION = "deny"

# The draft writer when DRAFT_MODEL is not set (spec 14.3). Same price as the
# tech matrix's Sonnet 5; record any change in the PR and the decision log.
DEFAULT_DRAFT_MODEL = "anthropic/claude-sonnet-5.5"

# The manual fallback when DRAFT_FALLBACK_MODEL is not set. A different
# provider family, so an Anthropic outage does not stop drafting.
DEFAULT_DRAFT_FALLBACK_MODEL = "openai/gpt-5.6-terra"

# Seconds per draft call, for the primary and the fallback alike (spec 14.7
# Q2). A grounded answer of up to 2000 tokens takes far longer than a triage
# label. Whether a call may start at all is decided by MIN_SECONDS_FOR_CALL
# against the 120 s draft Lambda's deadline.
DRAFT_TIMEOUT = 45

# No draft call starts with fewer seconds than this left before the deadline.
# Equal to DRAFT_TIMEOUT, so a call that is started can always run to its own
# timeout before the Lambda is killed; otherwise write_draft raises and the
# job is retried from the queue instead.
MIN_SECONDS_FOR_CALL = 45

# Request settings for the primary draft model, confirmed by step 0 (eval
# README "Models"). Sonnet 5.5 rejects temperature under require_parameters
# (404 "no endpoints", spec 14.8), so it is left out (None). 2000 tokens is
# well above the longest channel limit (spec 14.3 Q12).
DRAFT_SETTINGS = {"temperature": None, "max_tokens": 2000}

# Request settings for the fallback, confirmed by step 0. Terra also runs
# without temperature; low reasoning effort keeps latency near the primary's,
# and its reasoning tokens count against max_tokens, hence 4000 (spec 14.3).
DRAFT_FALLBACK_SETTINGS = {"temperature": None, "max_tokens": 4000, "extra": {"reasoning": {"effort": "low"}}}

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


def _openrouter(system, user, schema=None, *, model=None, temperature=0, timeout=TIMEOUT, max_tokens=None,
                extra=None, schema_name="triage"):
    """Call OpenRouter chat completions once.

    Temperature defaults to 0 so the same DM gets the same answer as far as
    the provider allows. With a schema, the response is forced into strict
    JSON, and require_parameters makes OpenRouter refuse providers that would
    silently ignore the schema (or any other setting sent). Every call sends
    data_collection "deny". There is deliberately no OpenRouter "models"
    list: it would send this same body to every model, and the draft models
    need different settings (spec 14.3), so write_draft falls back by hand.

    Called with only system, user and schema (as triage does), the body is
    the same as before these options existed, plus the data_collection key.

    Args:
        system (str): The system prompt.
        user (str): The user message (the rendered conversation).
        schema (dict | None): A JSON schema for structured output, or None
            for plain text.
        model (str | None): The model id; None means model_id() (triage).
        temperature (float | None): Sent as is; None leaves it out of the
            body, for models that reject it under require_parameters.
        timeout (float): Seconds before the request gives up.
        max_tokens (int | None): Output token cap, sent only when given.
        extra (dict | None): Extra top-level body fields for one model, for
            example {"reasoning": {"effort": "low"}}. Merged in before the
            provider block, so it can never drop data_collection.
        schema_name (str): The json_schema name OpenRouter passes on, for
            example "triage" or "draft".

    Returns:
        tuple[str | None, dict]: (content, meta). content is the model's reply
        text. meta is {"model": str, "latency_ms": int, "prompt_tokens": int,
        "completion_tokens": int, "cost": float | None}. meta["model"] is the
        model that actually answered (the response's "model"), falling back to
        the requested id only if the response leaves it out.

    Raises:
        LLMError: On any API failure, or a response with an error or no choices.
        RuntimeError: If OPENROUTER_API_KEY is missing.

    Side effects: one HTTPS request.
    """
    model = model or model_id()
    body = {"model": model}
    if temperature is not None:
        body["temperature"] = temperature
    body |= {"messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user}],
             "usage": {"include": True}}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    body |= extra or {}
    body["provider"] = {"data_collection": DATA_COLLECTION}
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": schema_name, "strict": True, "schema": schema}}
        body["provider"]["require_parameters"] = True
    started = time.monotonic()
    # timeout goes by keyword so callers and tests that unpack the four
    # positional arguments (service, url, headers, body) keep working.
    response = _json_request("openrouter", OPENROUTER_URL,
                             {"Authorization": f"Bearer {_key('OPENROUTER_API_KEY')}",
                              "Content-Type": "application/json"}, body, timeout=timeout)
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


def _retryable(error):
    """Say whether a failed embeddings request is worth trying again.

    Args:
        error (LLMError): The failure from _json_request.

    Returns:
        bool: True for a rate limit (429), a server error (5xx) or a network
        error (status None). False for any other 4xx, which would fail the
        same way again.

    Side effects: none.
    """
    return error.status is None or error.status == 429 or error.status >= 500


def _embed_batch(batch, headers, retry, timeout):
    """Send one embeddings request, retrying it if allowed.

    Args:
        batch (list[str]): At most EMBED_BATCH input texts.
        headers (dict[str, str]): Request headers, including Authorization.
        retry (bool): Retry retryable failures with EMBED_BACKOFF waits.
        timeout (float): Seconds per request.

    Returns:
        tuple[Any, int]: (response, retries). response is the parsed JSON;
        retries is how many failed tries came before it.

    Raises:
        LLMError: On the first failure when retry is False, on any failure
            that is not retryable, or on the last failure once every wait in
            EMBED_BACKOFF is used.

    Side effects: one HTTPS request per try, and a _sleep before each retry.
    """
    body = {"model": EMBED_MODEL, "input": batch}
    for retries, wait in enumerate((*EMBED_BACKOFF, None)):
        try:
            return _json_request("openai", EMBEDDINGS_URL, headers, body, timeout), retries
        except LLMError as error:
            if not retry or wait is None or not _retryable(error):
                raise
        _sleep(wait)


def _vectors(response, count):
    """Check one embeddings response and return its vectors in input order.

    Args:
        response (Any): The parsed JSON from the embeddings endpoint.
        count (int): How many inputs the request sent.

    Returns:
        list[list[float]]: count vectors, sorted by each item's index, so
        vector i belongs to input i of the request.

    Raises:
        LLMError: "bad_response" when data is missing, has the wrong number
            of items, or its indexes are not exactly 0 to count - 1;
            "bad_dimensions" when any vector does not have EMBED_DIMENSIONS
            numbers.

    Side effects: none.
    """
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise LLMError("openai", None, "bad_response")
    items = sorted(data, key=lambda item: item.get("index") if isinstance(item.get("index"), int) else -1)
    if [item.get("index") for item in items] != list(range(count)):
        raise LLMError("openai", None, "bad_response")
    vectors = [item.get("embedding") for item in items]
    for vector in vectors:
        if (not isinstance(vector, list) or len(vector) != EMBED_DIMENSIONS
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in vector)):
            raise LLMError("openai", None, "bad_dimensions")
    return vectors


def embed(texts, *, retry=False, timeout=TIMEOUT):
    """Embed texts with EMBED_MODEL, in batches of at most EMBED_BATCH.

    Args:
        texts (list[str]): The input texts. For a knowledge entry this is
            title + "\\n" + content.
        retry (bool): False at runtime (a query embedding fails fast, like
            triage, and the job retries later). True for ingest only: a 429,
            5xx or network error is retried after each wait in EMBED_BACKOFF,
            at most 5 tries per batch.
        timeout (float): Seconds per request.

    Returns:
        tuple[list[list[float]], dict]: (vectors, meta). vectors[i] is the
        EMBED_DIMENSIONS-long vector of texts[i]. meta is {"model": str,
        "tokens": int, "latency_ms": int}, with tokens and latency_ms summed
        over every batch (latency includes any retry waits). An empty input
        makes no request and returns ([], meta with zeros).

    Raises:
        LLMError: On an API failure (see retry), "bad_response" for a
            response without usable data, or "bad_dimensions" for a vector of
            the wrong length.
        RuntimeError: If OPENAI_API_KEY is missing.

    Side effects: one HTTPS request per batch (more with retries) and one log
    line with counts and latency only (never input text).
    """
    texts = list(texts)
    meta = {"model": EMBED_MODEL, "tokens": 0, "latency_ms": 0}
    if not texts:
        return [], meta
    headers = {"Authorization": f"Bearer {_key('OPENAI_API_KEY')}", "Content-Type": "application/json"}
    vectors, batches, retries = [], 0, 0
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        started = time.monotonic()
        response, tries_failed = _embed_batch(batch, headers, retry, timeout)
        meta["latency_ms"] += int((time.monotonic() - started) * 1000)
        vectors += _vectors(response, len(batch))
        usage = response.get("usage") or {}
        meta["tokens"] += usage.get("total_tokens") or usage.get("prompt_tokens") or 0
        meta["model"] = response.get("model") or EMBED_MODEL
        batches += 1
        retries += tries_failed
    logger.info("Embed stage=embed PASS batches=%d inputs=%d tokens=%d retries=%d latency_ms=%d",
                batches, len(texts), meta["tokens"], retries, meta["latency_ms"])
    return vectors, meta


def _falls_back(error):
    """Say whether a failed primary draft call should be tried on the fallback.

    Args:
        error (LLMError): The primary's failure from _openrouter.

    Returns:
        bool: True for an outage that another provider may not share: a
        timeout or network error (status None), a rate limit (429), no
        endpoint for these settings (404) or a server error (5xx). False for
        any other status (400, 401, 403...), which points at the request or
        the key and would fail on the fallback too.

    Side effects: none.
    """
    return _retryable(error) or error.status == 404


def _has_time(deadline, clock):
    """Say whether a draft call may start before the deadline.

    Args:
        deadline (float | None): An absolute clock() value, or None for no
            limit.
        clock (callable[[], float]): The clock the deadline was set with.

    Returns:
        bool: True when there is no deadline or at least MIN_SECONDS_FOR_CALL
        seconds remain.

    Side effects: reads the clock once (only when there is a deadline).
    """
    return deadline is None or deadline - clock() >= MIN_SECONDS_FOR_CALL


def _draft_call(attempt, model, system, user, schema, settings):
    """Make one draft call, parse its JSON and log one line.

    Args:
        attempt (str): "primary" or "fallback", for the log and the meta.
        model (str): The model id to request.
        system (str): The system prompt.
        user (str): The user message.
        schema (dict): The strict JSON schema for the answer.
        settings (dict): That model's _openrouter options (DRAFT_SETTINGS or
            DRAFT_FALLBACK_SETTINGS).

    Returns:
        tuple[dict, dict]: (data, meta). data is the parsed JSON object. meta
        is _openrouter's meta plus {"attempt": attempt}.

    Raises:
        LLMError: On an API failure (logged with status and error code).
        InvalidOutput: "not_json" when the reply is not a JSON object (logged
            with the served model, tokens and cost).
        RuntimeError: If OPENROUTER_API_KEY is missing.

    Side effects: one OpenRouter call and one log line (never text).
    """
    started = time.monotonic()
    try:
        content, meta = _openrouter(system, user, schema, model=model, timeout=DRAFT_TIMEOUT,
                                    schema_name="draft", **settings)
    except LLMError as error:
        logger.warning("Draft stage=draft_call FAIL attempt=%s model=%s status=%s error=%s latency_ms=%d",
                       attempt, model, error.status or "network", error.code or "unknown",
                       int((time.monotonic() - started) * 1000))
        raise
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        data = None
    usage = (attempt, meta["model"], meta["latency_ms"], meta["prompt_tokens"], meta["completion_tokens"],
             meta["cost"])
    if not isinstance(data, dict):
        # Strict JSON makes this rare. draft.py owns the one retry for bad
        # output; another model would not fix it, so there is no fallback.
        logger.warning("Draft stage=draft_call FAIL attempt=%s model=%s error=not_json latency_ms=%d "
                       "prompt_tokens=%d completion_tokens=%d cost=%s", *usage)
        raise InvalidOutput("not_json")
    logger.info("Draft stage=draft_call PASS attempt=%s model=%s latency_ms=%d prompt_tokens=%d "
                "completion_tokens=%d cost=%s", *usage)
    return data, {**meta, "attempt": attempt}


def write_draft(system, user, schema, *, deadline=None, clock=time.monotonic):
    """Write one grounded answer draft, falling back to a second model on an outage.

    Flow (spec 6.1, 14.3 and 14.7 Q2):
        1. With fewer than MIN_SECONDS_FOR_CALL seconds before the deadline,
           raise at once without a call, so the job is retried from the queue.
        2. Call DRAFT_MODEL with DRAFT_SETTINGS.
        3. If it timed out, lost the network, was rate limited (429), had no
           endpoint (404) or hit a server error (5xx), and the deadline still
           allows a call by the same rule, call DRAFT_FALLBACK_MODEL with
           DRAFT_FALLBACK_SETTINGS. Otherwise re-raise the primary's error.
        4. Any other status (400, 401, 403...) re-raises at once.

    Args:
        system (str): The system prompt.
        user (str): The user message (question, clarification and passages).
        schema (dict): The strict JSON schema for the answer.
        deadline (float | None): The latest clock() value by which a call may
            still be safely running (draft.py derives it from the Lambda's
            time left). None means no limit, for eval and local runs.
        clock (callable[[], float]): Seconds, monotonic. Tests pass a fake.

    Returns:
        tuple[dict, dict]: (data, meta). data is the parsed JSON object, not
        yet validated (field checks live in draft.py). meta is {"model":
        served model id, "latency_ms", "prompt_tokens", "completion_tokens",
        "cost", "attempt": "primary" | "fallback"}, with tokens and cost from
        the call that answered.

    Raises:
        LLMError: ("openrouter", None, "deadline") when the primary cannot
            start in time; otherwise the primary's error when it is not an
            outage or the fallback cannot start in time, or the fallback's own
            error.
        InvalidOutput: "not_json" when the answering model's reply is not a
            JSON object. Never sent to the fallback.
        RuntimeError: If OPENROUTER_API_KEY is missing.

    Side effects: one or two OpenRouter calls, one log line per call (and one
    when the primary is skipped for the deadline). Never logs text.
    """
    primary = os.environ.get("DRAFT_MODEL") or DEFAULT_DRAFT_MODEL
    if not _has_time(deadline, clock):
        logger.warning("Draft stage=draft_call FAIL attempt=primary model=%s status=skipped error=deadline "
                       "latency_ms=0", primary)
        raise LLMError("openrouter", None, "deadline")
    try:
        return _draft_call("primary", primary, system, user, schema, DRAFT_SETTINGS)
    except LLMError as error:
        if not _falls_back(error) or not _has_time(deadline, clock):
            raise
    fallback = os.environ.get("DRAFT_FALLBACK_MODEL") or DEFAULT_DRAFT_FALLBACK_MODEL
    return _draft_call("fallback", fallback, system, user, schema, DRAFT_FALLBACK_SETTINGS)
