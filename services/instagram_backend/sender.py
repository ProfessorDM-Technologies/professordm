"""Manual creator reply. Only the creator JWT determines authorization."""

import base64
import binascii
import json
import logging
import re


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
MAX_TEXT_LENGTH = 999
MAX_TEXT_BYTES = 1000
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class DuplicateRequest(Exception):
    """The database unique index already reserved this client request ID."""


def _response(status_code, body):
    return {"statusCode": status_code, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, separators=(",", ":"))}


def _parse_request(event):
    body = event.get("body") or ""
    if not isinstance(body, str):
        raise ValueError("invalid request body")
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("invalid request body") from exc
    try:
        data = json.loads(body)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid request body") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid request body")
    message_id, request_id, text = (data.get("inbound_message_id"),
                                    data.get("client_request_id"), data.get("text"))
    if (not isinstance(message_id, str) or not UUID_RE.fullmatch(message_id)
            or not isinstance(request_id, str) or not UUID_RE.fullmatch(request_id)
            or not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_TEXT_LENGTH
            or len(text.strip().encode("utf-8")) > MAX_TEXT_BYTES):
        raise ValueError("invalid reply fields")
    return message_id, request_id, text.strip()


def _bearer(headers):
    value = next((str(v) for k, v in (headers or {}).items() if k.lower() == "authorization"), "")
    return value[7:] if value.startswith("Bearer ") and len(value) > 7 else None


def _result(row):
    return {"id": row["id"], "status": row.get("status"),
            "meta_message_id": row.get("meta_message_id")}


def _log_failure(phase, error):
    # Provider messages, credentials, JWTs, and reply text never enter logs.
    logger.warning("Instagram send stage=%s FAIL error_type=%s http_status=%s meta_error_code=%s meta_error_type=%s",
                   phase, type(error).__name__, getattr(error, "status", None),
                   getattr(error, "code", None), getattr(error, "error_type", None))


def _record_status(repository, outbound_id, **values):
    # Retrying this PATCH is safe; never repeat the Meta POST.
    for _ in range(2):
        try:
            return repository.update_outbound(outbound_id, **values)
        except Exception as error:
            _log_failure("status_update", error)
    return None


def handle_send(event, *, auth, repository, profile_tokens, graph):
    if event.get("httpMethod") != "POST":
        return _response(405, {"error": "Method not allowed"})
    try:
        message_id, request_id, text = _parse_request(event)
    except ValueError:
        logger.warning("Instagram send stage=request_validation FAIL")
        return _response(400, {"error": "Invalid reply request"})

    jwt = _bearer(event.get("headers"))
    try:
        user_id = auth.user_id(jwt) if jwt else None
    except Exception as error:
        _log_failure("authentication", error)
        return _response(503, {"error": "Authentication temporarily unavailable"})
    if not user_id:
        logger.warning("Instagram send stage=authentication FAIL")
        return _response(401, {"error": "Unauthorized"})
    logger.info("Instagram send stage=authentication PASS")

    logger.info("Instagram send stage=ownership_resolution START")
    creator = repository.get_creator_by_profile(user_id)
    inbound = repository.get_inbound(message_id)
    if not creator or not inbound:
        return _response(404, {"error": "Message unavailable"})
    follower = repository.get_follower(inbound["follower_id"])
    if not follower or follower["creator_id"] != creator["id"]:
        return _response(403, {"error": "Forbidden"})
    account = repository.get_ig_account(creator["id"])
    if not account:
        return _response(409, {"error": "Instagram account unavailable or ambiguous"})
    logger.info("Instagram send stage=ownership_resolution PASS")

    row = {"type": "answer", "draft_id": None, "status": "pending", "attempts": 0,
           "delivery_mode": "standard",
           "meta_message_id": None, "creator_id": creator["id"],
           "inbound_message_id": message_id, "follower_id": follower["id"],
           "client_request_id": request_id, "text": text}
    try:
        outbound = repository.create_outbound(row)
    except DuplicateRequest:
        existing = repository.get_outbound_by_client_request_id(request_id)
        if existing and existing.get("creator_id") == creator["id"]:
            if existing.get("inbound_message_id") != message_id or existing.get("text") != text:
                return _response(409, {"error": "Request ID already belongs to another reply"})
            logger.info("Instagram send stage=idempotency REUSED outbound_id=%s", existing["id"])
            return _response(200, _result(existing))
        return _response(409, {"error": "Request ID conflict"})
    if not outbound or not outbound.get("id"):
        return _response(503, {"error": "Reply could not be reserved"})
    logger.info("Instagram send stage=reservation PASS outbound_id=%s", outbound["id"])

    phase, attempts = "token_lookup", 0
    try:
        token = profile_tokens.for_account(account["ig_user_id"])
        if not token:
            raise RuntimeError("Instagram token unavailable")
        logger.info("Instagram send stage=token_lookup PASS")
        phase = "token_validation"
        graph.validate_send_account(token, account["ig_user_id"])
        logger.info("Instagram send stage=token_validation PASS")
        phase = "attempt_record"
        repository.update_outbound(outbound["id"], status="pending", attempts=1)
        attempts = 1
        phase = "meta_send"
        provider_id = graph.send(token, account["ig_user_id"], follower["ig_scoped_id"], text)
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("Meta message ID unavailable")
        logger.info("Instagram send stage=meta_send PASS outbound_id=%s", outbound["id"])
    except Exception as error:
        _log_failure(phase, error)
        if not _record_status(repository, outbound["id"], status="failed", attempts=attempts):
            return _response(503, {"id": outbound["id"], "status": "pending",
                                   "error": "Delivery could not be confirmed. Check the conversation."})
        return _response(502, {"id": outbound["id"], "status": "failed",
                               "error": "Instagram delivery failed"})
    updated = _record_status(repository, outbound["id"], status="sent",
                             meta_message_id=provider_id, attempts=1)
    if not updated:
        return _response(503, {"id": outbound["id"], "status": "pending",
                               "error": "Delivery confirmation unavailable. Check Instagram before retrying."})
    logger.info("Instagram send stage=status_update PASS outbound_id=%s status=sent", outbound["id"])
    return _response(200, _result(updated))
