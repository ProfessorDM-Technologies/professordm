"""Meta webhook behavior for the existing API Gateway REST event format."""

import base64
import binascii
from datetime import datetime, timezone
import hmac
import json
import logging
import re


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


def _enrich_username(follower_id, sender_id, recipient_id, *, repository,
                     profile_tokens, graph, remaining_time_ms):
    phase = "token_lookup"
    try:
        # Core ingestion has already finished. Leave time for a safe HTTP response.
        if remaining_time_ms is not None and remaining_time_ms() < 12000:
            logger.info("Instagram webhook stage=username_enrichment SKIP time_budget")
            return
        token = profile_tokens.for_account(recipient_id)
        if not token:
            logger.warning("Instagram webhook stage=username_enrichment token_available=false")
            return
        phase = "meta_profile_lookup"
        profile = graph.user_profile(token, recipient_id, sender_id)
        if not isinstance(profile, dict) or profile.get("id") != sender_id:
            logger.warning("Instagram webhook stage=username_enrichment SKIP sender_mismatch")
            return
        username = profile.get("username")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", username):
            logger.info("Instagram webhook stage=username_enrichment username_returned=false updated=false")
            return
        phase = "username_update"
        updated = repository.update_follower_username_if_missing(follower_id, username)
        logger.info("Instagram webhook stage=username_enrichment username_returned=true updated=%s", updated)
    except Exception as error:
        logger.warning("Instagram webhook stage=username_enrichment FAIL phase=%s error_type=%s http_status=%s error_code=%s meta_error_type=%s",
                       phase, type(error).__name__, getattr(error, "status", None),
                       getattr(error, "code", None), getattr(error, "error_type", None))


def handle_webhook(event, *, verify_token, repository, publisher, profile_tokens, graph,
                   remaining_time_ms=None):
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
    try:
        payload = json.loads(raw)
        messages = list(_messages(payload))
    except (ValueError, UnicodeDecodeError):
        logger.warning("Instagram webhook stage=json_parse FAIL")
        return _response(400, "Invalid payload")

    logger.info("Instagram webhook stage=json_parse PASS message_candidates=%d", len(messages))

    pending_profiles = {}
    for mid, sender_id, recipient_id, text in messages:
        account = repository.find_account_by_ig_user_id(recipient_id)
        if not account:
            logger.warning("Instagram webhook stage=account_resolution FAIL recipient_not_connected")
            continue
        logger.info("Instagram webhook stage=account_resolution PASS")
        creator_id = account["creator_id"]
        follower = repository.upsert_follower(
            creator_id, sender_id, datetime.now(timezone.utc).isoformat()
        )
        logger.info("Instagram webhook stage=follower_upsert PASS")
        inbound = repository.upsert_inbound(mid, follower["id"], text)
        if not inbound or inbound["follower_id"] != follower["id"]:
            logger.warning("Instagram webhook stage=inbound_upsert FAIL mid_conflict")
            continue
        logger.info("Instagram webhook stage=inbound_upsert PASS")
        publisher.publish(inbound["id"], creator_id)
        logger.info("Instagram webhook stage=sqs_publish PASS")
        if follower.get("username") is None:
            pending_profiles.setdefault(follower["id"], (sender_id, recipient_id))
        else:
            logger.info("Instagram webhook stage=username_enrichment SKIP already_present")

    for follower_id, (sender_id, recipient_id) in pending_profiles.items():
        _enrich_username(follower_id, sender_id, recipient_id, repository=repository,
                         profile_tokens=profile_tokens, graph=graph,
                         remaining_time_ms=remaining_time_ms)
    return _response(200, "OK")
