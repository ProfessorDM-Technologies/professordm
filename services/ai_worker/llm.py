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
DEFAULT_MODEL = "google/gemini-3.1-flash-lite"
MODERATION_MODEL = "omni-moderation-latest"
MAX_CLARIFICATION_CHARS = 200
MEDIA_WORDS = re.compile(r"\b(photos?|pics?|pictures?|images?|videos?|screenshots?)\b", re.IGNORECASE)
TIMEOUT = 10
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)



class LLMError(Exception):
    def __init__(self, service, status=None, code=None):
        super().__init__(f"{service} request failed ({status or 'network'}, {code or 'unknown'})")
        self.service = service
        self.status = status
        self.code = code


class InvalidOutput(Exception):
    pass


def _key(variable):
    value = os.environ.get(variable)
    if not value:
        raise RuntimeError(f"Missing {variable}")
    return value


def _json_request(service, url, headers, body, timeout=TIMEOUT):
    request = Request(url, data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
                      headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as error:
        try:
            detail = json.loads(error.read())
            inner = detail.get("error") if isinstance(detail, dict) else None
            code = inner.get("code") or inner.get("type") if isinstance(inner, dict) else None
        except (ValueError, AttributeError):
            code = None
        raise LLMError(service, error.code, code) from None
    except (OSError, ValueError) as error:
        raise LLMError(service, None, type(error).__name__) from None


def model_id():
    return os.environ.get("TRIAGE_MODEL") or DEFAULT_MODEL


def _openrouter(system, user, schema=None):
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


def _conversation(text, recent_messages):
    lines = []
    if recent_messages:
        lines.append("Earlier messages, oldest first:")
        lines += [f"{i}. {json.dumps(m, ensure_ascii=False)}" for i, m in enumerate(recent_messages, 1)]
    lines.append("Latest message:")
    lines.append(json.dumps(text, ensure_ascii=False))
    return "\n".join(lines)


def _classify_schema(profile):
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
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        raise InvalidOutput("not_json") from None
    if not isinstance(data, dict) or data.get("category") not in CATEGORIES:
        raise InvalidOutput("bad_category")
    confidence = data.get("confidence")
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


def classify(text, recent_messages, profile):
    content, meta = _openrouter(triage_prompt(profile), _conversation(text, recent_messages),
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
    started = time.monotonic()
    response = _json_request("openai", MODERATION_URL,
                             {"Authorization": f"Bearer {_key('OPENAI_API_KEY')}",
                              "Content-Type": "application/json"},
                             {"model": MODERATION_MODEL, "input": text})
    results = response.get("results") if isinstance(response, dict) else None
    result = results[0] if isinstance(results, list) and results and isinstance(results[0], dict) else {}
    categories, scores = result.get("categories"), result.get("category_scores")
    if not isinstance(categories, dict) or not isinstance(scores, dict):
        raise LLMError("openai", None, "bad_response")
    flagged = {name: float(scores.get(name) or 0) for name, hit in sorted(categories.items()) if hit is True}
    logger.info("Triage stage=moderation PASS flagged=%s latency_ms=%d",
                ",".join(flagged) or "none", int((time.monotonic() - started) * 1000))
    return flagged


def write_clarification(text, recent_messages, profile):
    content, meta = _openrouter(clarify_prompt(profile), _conversation(text, recent_messages))
    prompt = content.strip() if isinstance(content, str) else ""
    if not prompt or len(prompt) >= MAX_CLARIFICATION_CHARS or MEDIA_WORDS.search(prompt):
        logger.warning("Triage stage=clarify FAIL error_type=invalid_output chars=%d latency_ms=%d",
                       len(prompt), meta["latency_ms"])
        raise InvalidOutput("bad_clarification")
    logger.info("Triage stage=clarify PASS chars=%d latency_ms=%d", len(prompt), meta["latency_ms"])
    return prompt
