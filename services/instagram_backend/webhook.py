"""Meta webhook behavior for the existing API Gateway REST event format."""

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _response(status, body=""):
    return {"statusCode": status, "body": body, "headers": {"Content-Type": "text/plain"}}


def _raw_body(event):
    body = event.get("body") or ""
    if not isinstance(body, str):
        raise ValueError("body must be a string")
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(body, validate=True)
        except binascii.Error as exc:
            raise ValueError("invalid base64 body") from exc
    return body.encode("utf-8")


def _valid_signature(raw, headers, app_secret):
    supplied = next((str(value) for key, value in (headers or {}).items()
                     if key.lower() == "x-hub-signature-256"), "")
    if not supplied.startswith("sha256=") or len(supplied) != 71:
        return False
    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def _messages(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if payload.get("object") != "instagram":
        return
    entries = payload.get("entry")
    if not isinstance(entries, list):
        raise ValueError("entry must be a list")
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("messaging", []), list):
            continue
        for item in entry.get("messaging", []):
            if not isinstance(item, dict):
                continue
            message = item.get("message")
            if not isinstance(message, dict):
                continue
            mid = message.get("mid")
            sender = item.get("sender")
            recipient = item.get("recipient")
            if not isinstance(mid, str) or not mid or not isinstance(sender, dict) or not isinstance(recipient, dict):
                continue
            sender_id, recipient_id = sender.get("id"), recipient.get("id")
            if not isinstance(sender_id, str) or not sender_id or not isinstance(recipient_id, str) or not recipient_id:
                continue
            text = message.get("text")
            yield mid, sender_id, recipient_id, text if isinstance(text, str) else None


def handle_webhook(event, *, verify_token, app_secret, repository, publisher):
    method = event.get("httpMethod")
    if method == "GET":
        params = event.get("queryStringParameters") or {}
        if (params.get("hub.mode") == "subscribe"
                and hmac.compare_digest(str(params.get("hub.verify_token", "")), verify_token)
                and params.get("hub.challenge") is not None):
            return _response(200, str(params["hub.challenge"]))
        return _response(403, "Forbidden")
    if method != "POST":
        return _response(405, "Method not allowed")

    try:
        raw = _raw_body(event)
    except ValueError:
        return _response(400, "Invalid body")
    if not _valid_signature(raw, event.get("headers"), app_secret):
        return _response(401, "Unauthorized")
    try:
        payload = json.loads(raw)
        messages = list(_messages(payload))
    except (ValueError, UnicodeDecodeError):
        return _response(400, "Invalid payload")

    logger.info("Instagram webhook signed message_candidates=%d", len(messages))

    for mid, sender_id, recipient_id, text in messages:
        account = repository.find_account_by_ig_user_id(recipient_id)
        if not account:
            logger.warning("Instagram webhook recipient is not connected")
            continue
        creator_id = account["creator_id"]
        follower = repository.upsert_follower(
            creator_id, sender_id, datetime.now(timezone.utc).isoformat()
        )
        inbound = repository.upsert_inbound(mid, follower["id"], text)
        if not inbound or inbound["follower_id"] != follower["id"]:
            logger.warning("Instagram webhook mid conflicts with another follower")
            continue
        publisher.publish(inbound["id"], creator_id)
    return _response(200, "OK")
