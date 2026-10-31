"""Check that every model we depend on finds a provider under data_collection: deny.

Every OpenRouter call (triage included) sends provider.data_collection =
"deny", so only providers that don't retain prompts are used. If a model has
no such provider, or none that accepts our exact settings, every call to it
fails. This script makes one tiny call per model with exactly the settings
production and eval use, and reports which ones work. Rerun it whenever a
model id or a setting changes.

Contents:
    CHECKS            the checks: model, settings, and variants to try on failure
    run_chat          one OpenRouter call
    run_embedding     one OpenAI embeddings call
    run_moderation    one OpenAI moderation call
    main              runs every check, prints one row each, sets the exit code

Usage:
    set -a; source .env; set +a
    uv run --python 3.11 python eval/check_providers.py

Depends on: OPENROUTER_API_KEY, OPENAI_API_KEY and the standard library. It
deliberately does not import services/ai_worker, so the check does not depend
on the code it is meant to vouch for.

Never does: print keys, send any DM, guide or other private text (the test
prompt is fixed below), or retry. Exits 1 if any main check fails; variants
are reported but never change the exit code.
"""

import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
MODERATION_URL = "https://api.openai.com/v1/moderations"

# The fixed test prompt. It holds no private text, so OpenRouter's error
# messages for it are safe to print in full.
SYSTEM = "Reply with one JSON object."
USER = "Return ok as true."
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"], "additionalProperties": False}

# The embedding model and the dimension knowledge_entries.embedding expects
# (vector(1536) in migration 001).
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMENSIONS = 1536

# Triage's moderation model (llm.MODERATION_MODEL). Checked because triage
# uses the same OpenAI key as embeddings.
MODERATION_MODEL = "omni-moderation-latest"

# The eval question generator and the judge of Terra drafts. Fixed by spec
# 14.8: the newest stable Pro model when step 0 first ran. Newer previews are
# deliberately not used.
GEMINI_PRO = "google/gemini-2.5-pro"

# Seconds per call. Generous because reasoning models (Terra, Gemini Pro) can
# think for a while even on a one-line prompt; a timeout here is a FAIL, not
# a retry.
TIMEOUT = 90

# One entry per check. "settings" is merged into the request body as is, so
# it shows exactly what is sent besides model, messages, response_format and
# provider. "variants" are tried only when the main check fails, to tell us
# which change would make the model work; they never change the spec.
# Sonnet (3) and the judge (5) send no temperature: under require_parameters
# no provider accepts it for them (404 on the first run, spec 14.8). Check 5
# therefore has no "without temperature" variant; it would be the same request.
CHECKS = [
    {"id": "1", "name": "triage classify", "model": "google/gemini-3.1-flash-lite",
     "schema": True, "settings": {"temperature": 0}},
    {"id": "2", "name": "triage clarify", "model": "google/gemini-3.1-flash-lite",
     "schema": False, "settings": {"temperature": 0}},
    {"id": "3", "name": "draft primary", "model": "anthropic/claude-sonnet-5.5",
     "schema": True, "settings": {"max_tokens": 2000}},
    {"id": "4", "name": "draft fallback", "model": "openai/gpt-5.6-terra",
     "schema": True, "settings": {"reasoning": {"effort": "low"}, "max_tokens": 4000},
     "variants": [("4 without reasoning", {"max_tokens": 4000}),
                  ("4 reasoning minimal", {"reasoning": {"effort": "minimal"}, "max_tokens": 4000})]},
    {"id": "5", "name": "judge", "model": "openai/gpt-6.1-sol",
     "schema": True, "settings": {}},
    {"id": "6a", "name": "gemini pro, default temp", "model": GEMINI_PRO,
     "schema": True, "settings": {}},
    # Without temperature, 6b is the same request as 6a; run_chat reuses that
    # result instead of calling again.
    {"id": "6b", "name": "gemini pro, temperature 0", "model": GEMINI_PRO,
     "schema": True, "settings": {"temperature": 0},
     "variants": [("6b without temperature", {})]},
    {"id": "7", "name": "embeddings", "model": EMBED_MODEL, "openai": "embedding"},
    {"id": "8", "name": "triage moderation", "model": MODERATION_MODEL, "openai": "moderation"},
]


def _key(variable):
    """Read an API key from the environment.

    Args:
        variable (str): The environment variable name.

    Returns:
        str: The key.

    Raises:
        SystemExit: If the variable is missing or empty. The message names the
            variable, never a value.

    Side effects: none.
    """
    value = os.environ.get(variable)
    if not value:
        sys.exit(f"Missing {variable}. Run: set -a; source .env; set +a")
    return value


def _error_text(payload):
    """Pull a printable error out of an OpenRouter or OpenAI error body.

    Args:
        payload (Any): The parsed JSON body, normally {"error": {...}}.

    Returns:
        str | None: "<code>: <message>", plus the provider's raw error when
        OpenRouter passes one through in metadata.raw (cut to 300 characters),
        or None if the body has no error.

    Side effects: none.
    """
    error = payload.get("error") if isinstance(payload, dict) else None
    if not error:
        return None
    if not isinstance(error, dict):
        return str(error)
    text = f"{error.get('code') or error.get('type') or 'error'}: {error.get('message') or ''}".strip()
    raw = (error.get("metadata") or {}).get("raw") if isinstance(error.get("metadata"), dict) else None
    if raw:
        text += f" | raw: {str(raw)[:300]}"
    return text


def _post(url, key, body):
    """POST a JSON body once and return what happened.

    Args:
        url (str): The endpoint.
        key (str): The bearer token. Sent only in the header, never printed.
        body (dict): The JSON body.

    Returns:
        tuple[int | None, dict | None, str | None, int]: (http_status, data,
        error, latency_ms). http_status is None for a network error or
        timeout. data is the parsed body on success. error is the provider's
        error text, or the exception name for network errors.

    Side effects: one HTTPS request.
    """
    request = Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    started = time.monotonic()
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            status, raw = response.status, response.read()
    except HTTPError as error:
        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            text = _error_text(json.loads(error.read()))
        except ValueError:
            text = None
        return error.code, None, text or "no error body", latency_ms
    except OSError as error:
        return None, None, type(error).__name__, int((time.monotonic() - started) * 1000)
    latency_ms = int((time.monotonic() - started) * 1000)
    try:
        return status, json.loads(raw), None, latency_ms
    except ValueError:
        return status, None, "response is not JSON", latency_ms


def chat_body(model, schema, settings):
    """Build the chat completions body exactly as production will send it.

    Args:
        model (str): The OpenRouter model id.
        schema (bool): True to require the strict JSON schema.
        settings (dict): temperature, max_tokens, reasoning... merged as is.

    Returns:
        dict: The body. With a schema, provider is {"data_collection": "deny",
        "require_parameters": true} so OpenRouter refuses providers that would
        ignore the schema; without one, {"data_collection": "deny"}.

    Side effects: none.
    """
    body = {"model": model, "messages": [{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": USER}], **settings}
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "check", "strict": True, "schema": SCHEMA}}
        body["provider"] = {"data_collection": "deny", "require_parameters": True}
    else:
        body["provider"] = {"data_collection": "deny"}
    return body


def run_chat(body, schema, key, cache):
    """Make one OpenRouter call and judge the reply.

    A reply passes when the HTTP status is 200, the body has no error, and
    the content is valid JSON with a boolean "ok" (schema checks) or any
    non-empty text (plain-text checks).

    Args:
        body (dict): From chat_body().
        schema (bool): Whether the reply must match SCHEMA.
        key (str): OPENROUTER_API_KEY.
        cache (dict): Results keyed by the serialized body, so an identical
            request (6b without temperature is 6a) is not sent twice.

    Returns:
        dict: {"served": str | None, "ok": bool, "status": int | None,
        "error": str | None, "latency_ms": int}.

    Side effects: at most one HTTPS request.
    """
    signature = json.dumps(body, sort_keys=True)
    if signature in cache:
        return cache[signature]
    status, data, error, latency_ms = _post(OPENROUTER_URL, key, body)
    served = data.get("model") if isinstance(data, dict) else None
    # OpenRouter can return 200 with an error in the body (a provider failed
    # after routing), so a 200 alone is not a pass.
    error = error or _error_text(data)
    if not error:
        choices = data.get("choices") if isinstance(data, dict) else None
        content = (choices[0].get("message") or {}).get("content") if choices else None
        if not isinstance(content, str) or not content.strip():
            error = "empty reply"
        elif schema:
            try:
                parsed = json.loads(content)
            except ValueError:
                parsed = None
            if not isinstance(parsed, dict) or not isinstance(parsed.get("ok"), bool):
                error = "reply does not match the schema"
    result = {"served": served, "ok": status == 200 and not error, "status": status,
              "error": error, "latency_ms": latency_ms}
    cache[signature] = result
    return result


def run_embedding(key):
    """Embed one word and confirm the vector has EMBED_DIMENSIONS values.

    Args:
        key (str): OPENAI_API_KEY.

    Returns:
        dict: Same shape as run_chat().

    Side effects: one HTTPS request.
    """
    status, data, error, latency_ms = _post(EMBEDDINGS_URL, key, {"model": EMBED_MODEL, "input": ["ok"]})
    served = data.get("model") if isinstance(data, dict) else None
    if not error:
        items = data.get("data") if isinstance(data, dict) else None
        vector = items[0].get("embedding") if items and isinstance(items[0], dict) else None
        if not isinstance(vector, list) or len(vector) != EMBED_DIMENSIONS:
            error = f"expected {EMBED_DIMENSIONS} dimensions, got {len(vector) if isinstance(vector, list) else 'none'}"
    return {"served": served, "ok": status == 200 and not error, "status": status,
            "error": error, "latency_ms": latency_ms}


def run_moderation(key):
    """Moderate one word and confirm the response has results[0].categories.

    That is the field llm.moderate reads; without it triage treats the call
    as an outage.

    Args:
        key (str): OPENAI_API_KEY.

    Returns:
        dict: Same shape as run_chat().

    Side effects: one HTTPS request.
    """
    status, data, error, latency_ms = _post(MODERATION_URL, key, {"model": MODERATION_MODEL, "input": "ok"})
    served = data.get("model") if isinstance(data, dict) else None
    if not error:
        results = data.get("results") if isinstance(data, dict) else None
        first = results[0] if isinstance(results, list) and results and isinstance(results[0], dict) else {}
        if not isinstance(first.get("categories"), dict):
            error = "no results[0].categories in the response"
    return {"served": served, "ok": status == 200 and not error, "status": status,
            "error": error, "latency_ms": latency_ms}


def _describe(check, settings):
    """Render a check's settings as a short readable string.

    Args:
        check (dict): The CHECKS entry.
        settings (dict): The settings actually sent (the check's or a variant's).

    Returns:
        str: For example "temperature 0, schema, max_tokens 2000".

    Side effects: none.
    """
    if check.get("openai") == "embedding":
        return f"input [\"ok\"], {EMBED_DIMENSIONS} dims"
    if check.get("openai") == "moderation":
        return "input \"ok\", results[0].categories"
    parts = ["temperature " + str(settings["temperature"]) if "temperature" in settings else "no temperature"]
    if "reasoning" in settings:
        parts.append(f"reasoning {settings['reasoning']['effort']}")
    parts.append("schema" if check["schema"] else "no schema")
    if "max_tokens" in settings:
        parts.append(f"max_tokens {settings['max_tokens']}")
    return ", ".join(parts)


def _row(label, requested, settings, result):
    """Print one result row.

    Args:
        label (str): The check id and name, or the variant name.
        requested (str): The model id requested.
        settings (str): From _describe().
        result (dict): From run_chat() or run_embedding().

    Returns:
        None.

    Side effects: prints to stdout.
    """
    print(f"{label:<30} {requested:<32} {(result['served'] or '-'):<38} "
          f"{'OK' if result['ok'] else 'FAIL':<5} {str(result['status'] or '-'):<5} "
          f"{result['latency_ms']:>7}  {settings}"
          + (f"\n{'':<30} error: {result['error']}" if result["error"] else ""))


def main():
    """Run every check, then the variants of any that failed.

    Returns:
        None.

    Raises:
        SystemExit: 1 if any main check failed, or if a key is missing.

    Side effects: up to about a dozen tiny model calls; prints to stdout.
    """
    openrouter_key, openai_key = _key("OPENROUTER_API_KEY"), _key("OPENAI_API_KEY")
    cache, failed = {}, []
    print(f"{'check':<30} {'requested':<32} {'served':<38} {'result':<5} {'http':<5} "
          f"{'ms':>7}  settings")
    for check in CHECKS:
        if check.get("openai") == "embedding":
            result = run_embedding(openai_key)
        elif check.get("openai") == "moderation":
            result = run_moderation(openai_key)
        else:
            result = run_chat(chat_body(check["model"], check["schema"], check["settings"]), check["schema"],
                              openrouter_key, cache)
        _row(f"{check['id']} {check['name']}", check["model"], _describe(check, check.get("settings", {})), result)
        if not result["ok"]:
            failed.append(check)
    for check in failed:
        for name, settings in check.get("variants", []):
            result = run_chat(chat_body(check["model"], check["schema"], settings), check["schema"],
                              openrouter_key, cache)
            _row(f"  variant: {name}", check["model"], _describe(check, settings), result)
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed"
          + (f"; failed: {', '.join(check['id'] for check in failed)}" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
