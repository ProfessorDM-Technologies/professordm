"""Lambda entry for the final answer screen (checkpoint 3).

The send API invokes this function synchronously with the exact text it is
about to send, and gets back one decision: PASS, HOLD or BLOCK (the shared
contract in docs/final-answer-screen.md). This file checks the payload, loads
the two model keys once per container, runs final_screen.screen_final and
logs one summary line. All decision logic lives in final_screen.py.

Contents:
    SECRETS, CHANNELS, MAX_TEXT_CHARS, TRACE_ID_MAX_CHARS
    lambda_handler(event, context)
        The entry point (handler "screen_handler.lambda_handler").

Depends on:
    boto3 from the Lambda runtime, imported inside _load_secrets so tests can
    run without it.
    final_screen for the decision, llm for the two model calls, prompts for
    the creator profile.
    Environment variables SSM_OPENAI_KEY and SSM_OPENROUTER_KEY (the names of
    the SSM parameters holding the keys), and optionally TRIAGE_MODEL (the
    model for the answer-rules check; llm.DEFAULT_MODEL when unset).

Never does:
    - Read Supabase, SQS or Instagram. It holds only the two model keys, so
      the send Lambda never needs them.
    - Send, store or change the text. The caller saves the returned flags as
      checkpoint-3 rows when the text is sent.
    - Log the text, the question, a secret or any other payload value. The
      summary line carries the decision, reason codes, moderation category
      names, rule ids, counts, latency, the cleaned trace id and
      check_version.
    - Raise for a bad payload or a failed check. A bad payload returns
      {"error": "invalid_request"}; a failed check returns HOLD for the
      system. The caller treats both, and any invoke error, as "check
      unavailable" and does not send.
"""

from functools import lru_cache
import logging
import os
import re
import time

import final_screen
import llm
from prompts import profile_for


# The variable llm.py reads, and the variable naming its SSM parameter. Only
# the two model keys: this function has no database access on purpose.
SECRETS = (("OPENAI_API_KEY", "SSM_OPENAI_KEY"),
           ("OPENROUTER_API_KEY", "SSM_OPENROUTER_KEY"))

# The channels the contract accepts. Only the send API calls this for Dec 1,
# and it sends "instagram"; "knowledge_app" is accepted so publishing to the
# knowledge app (SCRUM-143) can be screened later without a contract change.
# The channel does not change the screening; it is validated and logged.
CHANNELS = ("instagram", "knowledge_app")

# The contract's limit on text: 1 to 4000 characters (not bytes). 4000 is the
# knowledge app's answer limit, the longer of the two channels.
MAX_TEXT_CHARS = 4000

# Characters of trace_id kept for the log line. A trace id is a short opaque
# token; the cut, together with _TRACE_UNSAFE, stops a caller from putting
# message text into the logs through this field.
TRACE_ID_MAX_CHARS = 64

# creators.id as the contract sends it: a UUID in its canonical hyphenated
# form, either case.
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

# Everything except these characters is removed from trace_id before logging.
_TRACE_UNSAFE = re.compile(r"[^A-Za-z0-9._:-]")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@lru_cache(maxsize=1)
def _load_secrets():
    """Copy the two model keys from SSM into the environment, once per container.

    The same pattern as handler._load_secrets, without the Supabase secrets. A
    failure is not cached, so the next request tries again.

    Returns:
        None

    Raises:
        RuntimeError: If a parameter name is not configured or has no value.
            The message names the variable, never a value.

    Side effects: up to two SSM calls, and sets os.environ.
    """
    import boto3
    ssm = boto3.client("ssm")
    for variable, name_variable in SECRETS:
        name = os.environ.get(name_variable)
        if not name:
            raise RuntimeError(f"Missing {name_variable} parameter name")
        value = ssm.get_parameter(Name=name, WithDecryption=True).get("Parameter", {}).get("Value")
        if not value:
            raise RuntimeError(f"No value for {name_variable}")
        os.environ[variable] = value


def _encodable(text):
    """Say whether a string can be encoded as UTF-8.

    A broken JSON escape can leave a lone surrogate in a string. Such a text
    cannot be hashed, sent to a model or sent to Instagram.

    Args:
        text (str): The string to check.

    Returns:
        bool: True when text.encode("utf-8") works.

    Side effects: none.
    """
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _invalid_field(event):
    """Check the request payload against the contract.

    Args:
        event (Any): The Lambda event.

    Returns:
        str | None: None when the payload is valid, otherwise the name of the
        first field that is not: "event" (not a JSON object), "text" (not a
        string of 1 to MAX_TEXT_CHARS characters that encodes as UTF-8; it
        is never stripped, so a single space is valid), "creator_id" (not a
        canonical UUID string), "channel" (not one of CHANNELS),
        "question_text" (present and neither null nor an encodable string) or
        "trace_id" (present and neither null nor a string). Unknown keys are
        ignored.

    Side effects: none.
    """
    if not isinstance(event, dict):
        return "event"
    text = event.get("text")
    if not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT_CHARS or not _encodable(text):
        return "text"
    creator_id = event.get("creator_id")
    if not isinstance(creator_id, str) or not _UUID.fullmatch(creator_id):
        return "creator_id"
    channel = event.get("channel")
    if not isinstance(channel, str) or channel not in CHANNELS:
        return "channel"
    question = event.get("question_text")
    if question is not None and (not isinstance(question, str) or not _encodable(question)):
        return "question_text"
    if event.get("trace_id") is not None and not isinstance(event["trace_id"], str):
        return "trace_id"
    return None


def _trace(trace_id):
    """Clean the caller's trace id for the log line.

    Args:
        trace_id (str | None): The payload's trace_id.

    Returns:
        str: Only letters, digits and "._:-", at most TRACE_ID_MAX_CHARS
        characters, or "none" when nothing is left.

    Side effects: none.
    """
    return _TRACE_UNSAFE.sub("", trace_id or "")[:TRACE_ID_MAX_CHARS] or "none"


def _joined(values):
    """Join values for the log line, with "none" for an empty list."""
    return ",".join(values) or "none"


def lambda_handler(event, context):
    """Screen one final text and return the contract's response.

    Args:
        event (dict): {"text": str, "creator_id": uuid str, "channel":
            "instagram" | "knowledge_app", "question_text": str | None,
            "trace_id": str | None}. text is the exact string the caller will
            send; it is hashed and screened as given.
        context (Any): The Lambda context (unused).

    Returns:
        dict: {"error": "invalid_request"} for a payload that breaks the
        contract; otherwise the response with every key present:
        {"decision", "next_actor", "reason_codes", "categories", "rules",
        "flags", "text_sha256", "check_version", "model", "latency_ms"}.
        latency_ms covers the whole call, including a first-request secret
        load.

    Side effects: up to two SSM calls on a container's first request, the
    model calls final_screen makes, and one summary log line (plus one
    config-error line if the secrets could not be loaded).
    """
    started = time.monotonic()
    field = _invalid_field(event)
    if field:
        logger.warning("Final screen invalid_request field=%s", field)
        return {"error": "invalid_request"}
    text, question = event["text"], event.get("question_text") or None
    try:
        _load_secrets()
    except Exception as error:
        # Carry on without the keys: each model call then refuses to start
        # (llm raises RuntimeError for a missing key), and screen_final turns
        # that into HOLD for the system with check_unavailable. A blocked
        # term still blocks, because that check needs no key.
        logger.error("Final screen config_error error_type=%s", type(error).__name__)
    result = final_screen.screen_final(
        text, question_text=question, profile=profile_for(event["creator_id"]),
        # Looked up on llm at call time, so tests that replace the two
        # functions reach their fakes. Each rules call gets llm.TIMEOUT; the
        # overall deadline is final_screen's.
        moderate=llm.moderate,
        check_rules=lambda text, question_text, profile: llm.check_answer_rules(
            text, question_text, profile, timeout=llm.TIMEOUT))
    response = {**result, "latency_ms": int((time.monotonic() - started) * 1000)}
    logger.info("Final screen decision=%s next_actor=%s reasons=%s categories=%s rules=%s flags=%d text_chars=%d "
                "question_chars=%d channel=%s model=%s latency_ms=%d check_version=%s trace_id=%s",
                response["decision"], response["next_actor"], _joined(response["reason_codes"]),
                _joined(response["categories"]), _joined(rule["id"] for rule in response["rules"]),
                len(response["flags"]), len(text), len(question or ""), event["channel"],
                response["model"] or "none", response["latency_ms"], response["check_version"],
                _trace(event.get("trace_id")))
    return response
