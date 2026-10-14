"""Manual creator reply. Only the creator JWT determines authorization."""

import base64
import binascii
import json
import re


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
MAX_TEXT_LENGTH = 999


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
            or not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_TEXT_LENGTH):
        raise ValueError("invalid reply fields")
    return message_id, request_id, text.strip()


def _bearer(headers):
    value = next((str(v) for k, v in (headers or {}).items() if k.lower() == "authorization"), "")
    return value[7:] if value.startswith("Bearer ") and len(value) > 7 else None


def _result(row):
    return {"id": row["id"], "status": row.get("status"),
            "meta_message_id": row.get("meta_message_id")}


def handle_send(event, *, auth, repository, vault, graph):
    if event.get("httpMethod") != "POST":
        return _response(405, {"error": "Method not allowed"})
    try:
        message_id, request_id, text = _parse_request(event)
    except ValueError:
        return _response(400, {"error": "Invalid reply request"})

    jwt = _bearer(event.get("headers"))
    user_id = auth.user_id(jwt) if jwt else None
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

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

    row = {"type": "answer", "draft_id": None, "status": "pending", "attempts": 0,
           "meta_message_id": None, "creator_id": creator["id"],
           "inbound_message_id": message_id, "follower_id": follower["id"],
           "client_request_id": request_id, "text": text}
    try:
        outbound = repository.create_outbound(row)
    except DuplicateRequest:
        existing = repository.get_outbound_by_client_request_id(request_id)
        if existing and existing.get("creator_id") == creator["id"]:
            return _response(200, _result(existing))
        return _response(409, {"error": "Request ID conflict"})

    try:
        token = vault.page_token(account["id"])
        if not token:
            raise RuntimeError("Page token unavailable")
        provider_id = graph.send(token, follower["ig_scoped_id"], text)
    except Exception:
        repository.update_outbound(outbound["id"], status="failed")
        return _response(502, {"id": outbound["id"], "status": "failed",
                               "error": "Instagram delivery failed"})
    updated = repository.update_outbound(outbound["id"], status="sent", meta_message_id=provider_id)
    return _response(200, _result(updated))
