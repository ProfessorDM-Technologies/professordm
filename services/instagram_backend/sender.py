"""Manual creator reply, and the creator's answer to a question. Only the creator JWT determines authorization."""

import base64
import binascii
from datetime import datetime, timedelta, timezone
import json
import logging
import re


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
MAX_TEXT_LENGTH = 999
MAX_TEXT_BYTES = 1000
MAX_TAGS = 5
MAX_TAG_LENGTH = 40
# Days a delivered answer is held before it counts as accepted.
HOLD_DAYS = 3
# JavaScript's \s, so the edit rule and tag trimming match the inbox's answer.ts exactly.
_JS_SPACE = "[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"
_JS_SPACES = re.compile(f"{_JS_SPACE}+")
_JS_EDGES = re.compile(f"^{_JS_SPACE}+|{_JS_SPACE}+$")
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
    return message_id, request_id, text.strip(), data


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
        message_id, request_id, text, data = _parse_request(event)
        answer = _parse_answer(data)
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
    if answer is not None:
        return _answer_question(answer, user_id=user_id, creator=creator, follower=follower, account=account,
                                message_id=message_id, request_id=request_id, text=text,
                                repository=repository, profile_tokens=profile_tokens, graph=graph)

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


# Answering a question: POST /api/send with question_id (docs/plans/creator-inbox-spec.md section 4).

def _parse_answer(data):
    """Return the answer fields, or None when question_id is absent (today's manual reply)."""
    question_id = data.get("question_id")
    if question_id is None:
        return None
    flag_ids = data.get("reviewed_flag_ids")
    flag_ids = [] if flag_ids is None else flag_ids
    if (not isinstance(question_id, str) or not UUID_RE.fullmatch(question_id) or not isinstance(flag_ids, list)
            or not all(isinstance(flag_id, str) and UUID_RE.fullmatch(flag_id) for flag_id in flag_ids)):
        raise ValueError("invalid answer fields")
    return {"question_id": question_id.lower(), "tags": data.get("tags"),
            "reviewed_flag_ids": {flag_id.lower() for flag_id in flag_ids}}


def normalize_answer(text):
    """Collapse every run of whitespace to one space and trim, like normalizeAnswer in answer.ts."""
    return _JS_EDGES.sub("", _JS_SPACES.sub(" ", text))


def _utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


def parse_tags(raw):
    """Return 1 to 5 unique tags, each trimmed, lower-cased and 1 to 40 characters, or None if invalid or missing."""
    if not isinstance(raw, list) or not all(isinstance(tag, str) for tag in raw):
        return None
    tags = list(dict.fromkeys(_JS_EDGES.sub("", tag).lower() for tag in raw))
    if not 1 <= len(tags) <= MAX_TAGS or not all(1 <= _utf16_length(tag) <= MAX_TAG_LENGTH for tag in tags):
        return None
    return tags


def edit_distance(before, after):
    """Character Levenshtein distance between two texts."""
    if len(before) < len(after):
        before, after = after, before
    previous = list(range(len(after) + 1))
    for i, left in enumerate(before, 1):
        current = [i]
        for j, right in enumerate(after, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def _now():
    return datetime.now(timezone.utc)


def _existing_answer(existing, creator_id, message_id, text):
    """The response for a client_request_id this API has already seen, as the manual reply returns it."""
    if existing.get("creator_id") != creator_id:
        return _response(409, {"error": "Request ID conflict"})
    if existing.get("inbound_message_id") != message_id or existing.get("text") != text:
        return _response(409, {"error": "Request ID already belongs to another reply"})
    logger.info("Instagram send stage=idempotency REUSED outbound_id=%s", existing["id"])
    return _response(200, _result(existing))


def _reopen_question(repository, question_id, expected_status):
    """Hand a question back to the creator when nothing was sent. Best effort: never raises."""
    try:
        if repository.update_question(question_id, expected_status, {"status": "awaiting_creator"}):
            return True
    except Exception as error:
        _log_failure("question_reopen", error)
    return False


def _save_answer(repository, *, question, draft, user_id, creator_id, text, tags, open_flag_ids):
    """Steps 6 to 9: the approved answer, reviewed flags, tags and the audit row. Returns the drafts row id."""
    ai_text = draft.get("ai_text") if draft else None
    distance = edit_distance(ai_text, text) if ai_text is not None else None
    approved = {"final_text": text, "status": "approved", "approved_at": _now().isoformat()}
    if draft:
        draft_id = repository.update_draft(draft["id"], {**approved, "edit_distance": distance})["id"]
    else:
        draft_id = repository.insert_draft({"question_id": question["id"], "ai_text": None, "citations": [],
                                            **approved})["id"]
    reviewed = repository.mark_flags_reviewed(sorted(open_flag_ids), user_id)
    tag_ids = [repository.find_or_create_tag(creator_id, name)["id"] for name in tags]
    repository.add_question_tags(question["id"], tag_ids)
    repository.insert_audit({"actor_id": user_id, "action": "answer.approved", "entity": "question",
                             "entity_id": question["id"],
                             "before_after": {"edit_distance": distance, "tag_count": len(tags),
                                              "had_ai_draft": bool(ai_text), "flags_reviewed": len(reviewed)}})
    return draft_id


def _deliver_answer(repository, profile_tokens, graph, *, question_id, outbound, account, follower, text):
    """Step 10 after the outbound row is reserved: call Meta once and record what happened."""
    from clients import RestError  # here, because clients imports this module
    outbound_id = outbound["id"]
    phase, attempts = "question_delivering", 0
    try:
        if not repository.update_question(question_id, "approved", {"status": "delivering"}):
            raise RuntimeError("question no longer approved")
        phase = "token_lookup"
        token = profile_tokens.for_account(account["ig_user_id"])
        if not token:
            raise RuntimeError("Instagram token unavailable")
        phase = "token_validation"
        graph.validate_send_account(token, account["ig_user_id"])
        phase = "attempt_record"
        repository.update_outbound(outbound_id, status="pending", attempts=1)
        attempts = 1
        phase = "meta_send"
        provider_id = graph.send(token, account["ig_user_id"], follower["ig_scoped_id"], text)
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("Meta message ID unavailable")
    except Exception as error:
        _log_failure(phase, error)
        meta_refused = isinstance(error, RestError) and (
            phase == "token_validation" or (phase == "meta_send" and 400 <= (error.status or 0) < 500))
        if phase == "meta_send" and not meta_refused:
            # Meta may have delivered it. The row stays pending with attempts 1, so a retry with the same
            # client_request_id returns it instead of sending a second DM.
            logger.warning("Instagram send stage=answer_delivery UNCONFIRMED outbound_id=%s", outbound_id)
            return _response(500, {"id": outbound_id, "status": "pending", "error": "delivery_unconfirmed"})
        # Nothing reached the follower: the row fails and the question goes back to the creator.
        _record_status(repository, outbound_id, status="failed", attempts=attempts)
        _reopen_question(repository, question_id, "delivering" if phase != "question_delivering" else "approved")
        if meta_refused:
            return _response(502, {"error": "delivery_failed"})
        return _response(500, {"id": outbound_id, "status": "failed", "error": "Send processing failed"})
    logger.info("Instagram send stage=meta_send PASS outbound_id=%s", outbound_id)
    updated = _record_status(repository, outbound_id, status="sent", meta_message_id=provider_id, attempts=1)
    delivered_at = _now()
    delivered = None
    for _ in range(2):
        try:
            delivered = repository.update_question(question_id, "delivering", {
                "status": "delivered", "delivered_at": delivered_at.isoformat(),
                "hold_ends_at": (delivered_at + timedelta(days=HOLD_DAYS)).isoformat()})
            break
        except Exception as error:
            _log_failure("question_delivered", error)
    if not delivered:
        logger.warning("Instagram send stage=question_delivered FAIL question_id=%s", question_id)
    if not updated:
        return _response(500, {"id": outbound_id, "status": "pending",
                               "error": "Delivery confirmation unavailable. Check Instagram before retrying."})
    logger.info("Instagram send stage=answer_delivery PASS question_id=%s outbound_id=%s", question_id, outbound_id)
    return _response(200, _result(updated))


def _answer_question(answer, *, user_id, creator, follower, account, message_id, request_id, text,
                     repository, profile_tokens, graph):
    question_id = answer["question_id"]
    existing = repository.get_outbound_by_client_request_id(request_id)
    if existing:
        return _existing_answer(existing, creator["id"], message_id, text)

    question = repository.get_question(question_id)
    if not question or question.get("creator_id") != creator["id"]:
        return _response(404, {"error": "Question unavailable"})
    if question.get("origin_message_id") != message_id:
        return _response(400, {"error": "Invalid reply request"})
    if question.get("source") != "instagram":
        return _response(400, {"error": "Invalid reply request"})
    if question.get("status") != "awaiting_creator":
        return _response(409, {"error": "not_awaiting_answer"})

    draft = repository.get_question_draft(question_id)
    tags = parse_tags(answer["tags"])
    if tags is None:
        return _response(422, {"error": "tags_required"})
    ai_text = draft.get("ai_text") if draft else None
    if isinstance(ai_text, str) and normalize_answer(ai_text) and normalize_answer(text) == normalize_answer(ai_text):
        return _response(422, {"error": "edit_required"})
    open_flag_ids = {flag_id.lower() for flag_id in repository.get_open_flag_ids(
        message_id, draft["id"] if draft else None)}
    if not open_flag_ids <= answer["reviewed_flag_ids"]:
        return _response(422, {"error": "flags_unreviewed"})
    logger.info("Instagram send stage=answer_gate PASS question_id=%s", question_id)

    if not repository.update_question(question_id, "awaiting_creator", {"status": "approved"}):
        return _response(409, {"error": "not_awaiting_answer"})
    try:
        draft_id = _save_answer(repository, question=question, draft=draft, user_id=user_id,
                                creator_id=creator["id"], text=text, tags=tags, open_flag_ids=open_flag_ids)
        outbound = repository.create_outbound({
            "type": "answer", "draft_id": draft_id, "status": "pending", "attempts": 0, "delivery_mode": "standard",
            "meta_message_id": None, "creator_id": creator["id"], "inbound_message_id": message_id,
            "follower_id": follower["id"], "client_request_id": request_id, "text": text})
        if not outbound or not outbound.get("id"):
            raise RuntimeError("outbound row not reserved")
    except DuplicateRequest:
        # A request with the same id reserved the row first; it owns the send.
        _reopen_question(repository, question_id, "approved")
        existing = repository.get_outbound_by_client_request_id(request_id)
        if not existing:
            return _response(409, {"error": "Request ID conflict"})
        return _existing_answer(existing, creator["id"], message_id, text)
    except Exception as error:
        # Nothing was sent, so the creator can try again.
        _log_failure("answer_save", error)
        _reopen_question(repository, question_id, "approved")
        return _response(500, {"error": "Send processing failed"})
    logger.info("Instagram send stage=reservation PASS outbound_id=%s question_id=%s", outbound["id"], question_id)
    return _deliver_answer(repository, profile_tokens, graph, question_id=question_id, outbound=outbound,
                           account=account, follower=follower, text=text)
