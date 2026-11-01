"""Automated replies. Sends the clarification and decline rows the AI worker creates.

Answers are sent only by POST /api/send. A row is claimed (attempts 0 -> 1)
before Meta is called and is never retried after that: a duplicate DM is worse
than a failed one, and the creator sees `failed` in the thread.
"""

import logging

from sender import MAX_TEXT_BYTES, _log_failure, _record_status


JOB_VERSION = 1
SENDABLE_TYPES = ("clarification", "decline")
DONE = "done"
RETRY = "retry"
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _outbound_id(job):
    if not isinstance(job, dict) or job.get("v") != JOB_VERSION or job.get("type") not in SENDABLE_TYPES:
        return None
    payload = job.get("payload")
    outbound_id = payload.get("outboundMessageId") if isinstance(payload, dict) else None
    return outbound_id if isinstance(outbound_id, str) and outbound_id else None


def _load(rest, outbound_id):
    rows = rest.request("GET", "outbound_messages", params={
        "id": f"eq.{outbound_id}", "select": "id,type,text,status,attempts,follower_id,creator_id", "limit": "1"})
    return rows[0] if isinstance(rows, list) and rows else None


def _claim(rest, outbound_id):
    rows = rest.request("PATCH", "outbound_messages", params={
        "id": f"eq.{outbound_id}", "status": "eq.pending", "attempts": "eq.0"},
        body={"attempts": 1}, prefer="return=representation")
    return bool(rows)


def _text_ok(text):
    return isinstance(text, str) and bool(text.strip()) and len(text.strip().encode("utf-8")) <= MAX_TEXT_BYTES


def _log_result(outbound_id, outbound_type, outcome):
    logger.info("Instagram outbound id=%s type=%s outcome=%s", outbound_id, outbound_type, outcome)


def _deliver(row, account, follower, repository, profile_tokens, graph):
    outbound_id, outbound_type = row["id"], row["type"]
    phase = "token_lookup"
    try:
        token = profile_tokens.for_account(account["ig_user_id"])
        if not token:
            raise RuntimeError("Instagram token unavailable")
        phase = "token_validation"
        graph.validate_send_account(token, account["ig_user_id"])
        phase = "meta_send"
        provider_id = graph.send(token, account["ig_user_id"], follower["ig_scoped_id"], row["text"].strip())
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("Meta message ID unavailable")
    except Exception as error:
        _log_failure(phase, error)
        _record_status(repository, outbound_id, status="failed", attempts=1)
        _log_result(outbound_id, outbound_type, "failed")
        return
    # A row left pending here is still never sent again, because attempts is 1.
    _record_status(repository, outbound_id, status="sent", meta_message_id=provider_id, attempts=1)
    _log_result(outbound_id, outbound_type, "sent")


def handle_outbound(job, *, rest, repository, profile_tokens, graph):
    outbound_id = _outbound_id(job)
    if not outbound_id:
        logger.warning("Instagram outbound stage=job_validation FAIL")
        return DONE

    # Nothing in this block calls Meta, so any error here is safe to retry.
    try:
        row = _load(rest, outbound_id)
        if not row or row.get("status") != "pending" or row.get("attempts") != 0:
            _log_result(outbound_id, job["type"], "already_handled")
            return DONE
        follower = repository.get_follower(row["follower_id"])
        account = repository.get_ig_account(row["creator_id"])
        if not follower or not account or follower["creator_id"] != row["creator_id"]:
            repository.update_outbound(outbound_id, status="failed")
            _log_result(outbound_id, row["type"], "recipient_unavailable")
            return DONE
        if not _text_ok(row.get("text")):
            repository.update_outbound(outbound_id, status="failed")
            _log_result(outbound_id, row["type"], "invalid_text")
            return DONE
        if not _claim(rest, outbound_id):
            _log_result(outbound_id, row["type"], "already_handled")
            return DONE
    except Exception as error:
        _log_failure("pre_claim", error)
        return RETRY

    _deliver(row, account, follower, repository, profile_tokens, graph)
    return DONE
