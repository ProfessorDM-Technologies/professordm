"""Job logic for the AI worker: triage, reassess and draft.

Runs the pure decision functions (triage.py, draft.py) and saves what they
decide. handler.py is the Lambda entry; this module holds the decisions about
claims, write order and retries, so tests can run it with fakes.

Entry points:
    parse_job(body)
        Validates one SQS message body (job envelope, spec section 3).
    run_job(job, *, receive_count, db, publish, time_left)
        Runs one job and returns "done" or "retry". Never raises.

Every job must be safe to run twice: SQS can deliver a job more than once and
the webhook publishes a new job each time Meta retries. A job claims its row
with a conditional update, every write checks first, and the status is written
last, so a job that dies midway is finished by the redelivered one.

Depends on:
    db       for every query (Db and DbError).
    triage, draft, prompts and llm, looked up at call time so tests can patch
    them.
    Environment variables PAYMENT_STUB, AI_JOBS_QUEUE_URL and
    OUTBOUND_QUEUE_URL, read at call time.

Never does:
    - Import boto3. handler.py passes in publish.
    - Call Instagram. The outbound sender does that.
    - Log DM text, clarification text, answer text, reason values or keys.
      Logs carry ids, statuses, counts, latency and error type names only.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import time
import uuid

from db import DbError
import draft
import llm
import prompts
import triage


JOB_VERSION = 1

# The payload id each job type needs (spec section 3).
PAYLOAD_IDS = {"triage": "messageId", "reassess": "messageId", "draft": "questionId"}

DONE = "done"
RETRY = "retry"

# Fixed forever: it makes each outbound row's client_request_id deterministic,
# so a retried job finds the same row instead of sending twice.
OUTBOUND_NS = uuid.UUID("f73729bd-0dac-45c2-9d2a-362857398e82")

# The window of earlier DMs passed to triage, so a question split across
# several DMs is read as one (README "For Akshay" item 3).
RECENT_WINDOW = timedelta(minutes=30)
RECENT_SKIP_STATUSES = ("blocked", "closed_no_action")

# A message or draft goes to the creator after this many AI outages. Matches
# the queue's maxReceiveCount, so it is decided before the job reaches the DLQ.
MAX_ATTEMPTS = 3
OUTAGE_REASON = "AI unavailable after 3 attempts"

# Seconds kept back from draft() for the writes that follow it (spec 6 step 3).
DRAFT_WRITE_RESERVE = 15

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def parse_job(body):
    """Validate one SQS message body against the job envelope (spec section 3).

    Args:
        body (str | None): The SQS record's body.

    Returns:
        dict | None: The job, or None when it can never succeed: malformed
        JSON, an unknown version or type, or a missing payload id. The caller
        acknowledges those instead of retrying.

    Side effects: one warning log line when invalid, with the type name only.
    """
    try:
        job = json.loads(body)
    except (TypeError, ValueError):
        logger.warning("AI worker job=invalid type=none detail=not_json")
        return None
    job_type = job.get("type") if isinstance(job, dict) else None
    payload = job.get("payload") if isinstance(job, dict) else None
    key = PAYLOAD_IDS.get(job_type) if isinstance(job_type, str) else None
    if (key is None or job.get("v") != JOB_VERSION or not isinstance(payload, dict)
            or not isinstance(payload.get(key), str) or not payload[key]):
        logger.warning("AI worker job=invalid type=%s", job_type if key else "unknown")
        return None
    return job


def _queue(variable):
    """Read a queue URL from the environment at call time.

    Args:
        variable (str): The environment variable name.

    Returns:
        str: The queue URL.

    Raises:
        RuntimeError: If the variable is missing or empty.

    Side effects: none.
    """
    url = os.environ.get(variable)
    if not url:
        raise RuntimeError(f"Missing {variable}")
    return url


def _job(job_type, job_id, creator_id, trace_id, payload):
    """Build a job envelope that keeps the trace id of the job that caused it."""
    return {"v": JOB_VERSION, "type": job_type, "id": job_id, "creatorId": creator_id, "traceId": trace_id,
            "createdAt": datetime.now(timezone.utc).isoformat(), "payload": payload}


def _insert_missing_flags(db, flags, target_type, target_id, checkpoint):
    """Insert the safety flags a target does not have yet.

    Args:
        db (Db): The database client.
        flags (list[dict]): The decision's {"layer", "category", "detail"} flags.
        target_type (str): "message" or "draft".
        target_id (str): The target row id.
        checkpoint (str): "1" or "2".

    Returns:
        None

    Side effects: one read, and one insert when any flag is new.
    """
    seen = {(row["layer"], row["category"], row["detail"])
            for row in db.get_flags(target_type, target_id, checkpoint)}
    rows = []
    for flag in flags:
        key = (flag["layer"], flag["category"], flag["detail"])
        if key not in seen:
            seen.add(key)
            rows.append({"target_type": target_type, "target_id": target_id, "checkpoint": checkpoint,
                         "layer": flag["layer"], "category": flag["category"], "detail": flag["detail"]})
    if rows:
        db.insert_flags(rows)


class _TriageRun:
    """One triage or reassess job, and which rows it has claimed so far."""

    def __init__(self, db, publish, message, follower, trace_id, receive_count):
        self.db = db
        self.publish = publish
        self.message = message
        self.follower = follower
        self.creator_id = follower["creator_id"]
        self.trace_id = trace_id
        self.receive_count = receive_count
        self.profile = prompts.profile_for(self.creator_id)
        self.claimed = False       # this run holds the message as triaging
        self.original = None       # the claimed message this one replies to (reassess path)
        self.rounds = []           # that message's clarification rounds, lowest first


def _open_clarification(run):
    """Say whether this message replies to an open clarification (spec 5.2).

    A redelivery also matches an original left in reassessing, and a round
    that already holds this reply. An earlier attempt that died mid-reassess
    leaves exactly that, and the redelivered job has to finish it.

    Args:
        run (_TriageRun): The job.

    Returns:
        tuple[dict | None, list[dict]]: (original, rounds), or (None, []) when
        this is a new message.

    Side effects: up to two reads.
    """
    message, db = run.message, run.db
    redelivered = run.receive_count > 1
    statuses = ("awaiting_clarification", "reassessing") if redelivered else ("awaiting_clarification",)
    original = db.find_open_original(message["follower_id"], message["id"], message["received_at"], statuses)
    if not original:
        return None, []
    rounds = db.get_rounds(original["id"])
    if not rounds:
        return None, []
    reply = rounds[-1]["reply"]
    if reply is None or (redelivered and reply == message["text"]):
        return original, rounds
    return None, []


def _claim_message(run):
    """Claim the message (spec 5.3 step 1). Returns True if this run holds it."""
    statuses = (None, "received", "triaging") if run.receive_count > 1 else (None, "received")
    run.claimed = bool(run.db.claim_message(run.message["id"], statuses))
    return run.claimed


def _claim_original(run, original, rounds):
    """Claim the original message for reassess (spec 5.5 step 2). Returns True if claimed."""
    statuses = ("awaiting_clarification", "reassessing") if run.receive_count > 1 else ("awaiting_clarification",)
    if not run.db.update_message_where(original["id"], statuses, {"status": "reassessing"}):
        return False
    run.original, run.rounds = original, rounds
    return True


def _recent(run, message):
    """Build recent_messages for a message (spec 5.3 step 2).

    Args:
        run (_TriageRun): The job.
        message (dict): The message the window is relative to, with "id" and
            "received_at".

    Returns:
        list[str]: The follower's other DMs from the 30 minutes before it,
        oldest first, without blocked, closed or empty ones. Clarification
        replies are closed_no_action, so they are left out too.

    Side effects: one read.
    """
    received_at = message["received_at"]
    since = (datetime.fromisoformat(received_at) - RECENT_WINDOW).isoformat()
    rows = run.db.recent_messages(run.message["follower_id"], message["id"], since, received_at)
    return [row["text"] for row in rows
            if isinstance(row.get("text"), str) and row["text"].strip() and row.get("status") not in RECENT_SKIP_STATUSES]


def _write_decision(run, decision, origin, in_progress):
    """Save a triage or reassess decision, in the order of spec 5.4.

    Jobs go out before the final status write. A crash after publishing only
    causes a harmless duplicate, and a crash before it leaves the in-progress
    status, which the redelivered job re-claims.

    Args:
        run (_TriageRun): The job.
        decision (dict): The decision from triage() or reassess().
        origin (dict): The message the decision belongs to.
        in_progress (str): origin's status while this run holds it.

    Returns:
        None

    Raises:
        DbError: If a write fails.
        RuntimeError: If a queue URL is missing.

    Side effects: database writes and up to two published jobs.
    """
    db, origin_id, follower_id = run.db, origin["id"], run.message["follower_id"]
    if decision["safety_flags"]:
        _insert_missing_flags(db, decision["safety_flags"], "message", origin_id, "1")

    clarification = decision["clarification"]
    if clarification and not db.find_round(origin_id, clarification["round"]):
        db.insert_round({"message_id": origin_id, "round": clarification["round"],
                         "prompt": clarification["prompt"], "reply": None})

    outbound_row = None
    if decision["outbound"]:
        outbound_type = decision["outbound"]["type"]
        round_ = clarification["round"] if clarification else 0
        outbound_row = db.insert_outbound({
            "type": outbound_type, "text": decision["outbound"]["text"], "status": "pending", "attempts": 0,
            "delivery_mode": "standard", "inbound_message_id": origin_id, "follower_id": follower_id,
            "creator_id": run.creator_id, "draft_id": None,
            "client_request_id": str(uuid.uuid5(OUTBOUND_NS, f"{origin_id}:{outbound_type}:{round_}"))})

    question = None
    if decision["question"]:
        question = db.find_question(origin_id) or db.insert_question({
            "creator_id": run.creator_id, "source": "instagram", "follower_id": follower_id,
            "origin_message_id": origin_id, "question_text": decision["question"]["question_text"],
            "status": "pending_payment", "safety_flagged": decision["question"]["safety_flagged"]})
        if os.environ.get("PAYMENT_STUB") == "true":
            question = db.mark_paid(question["id"], datetime.now(timezone.utc).isoformat()) or question

    if outbound_row:
        outbound_id = outbound_row["id"]
        run.publish(_queue("OUTBOUND_QUEUE_URL"),
                    _job(decision["outbound"]["type"], f"outbound:{outbound_id}", run.creator_id, run.trace_id,
                         {"outboundMessageId": outbound_id}))
    if question and question["status"] == "paid":
        run.publish(_queue("AI_JOBS_QUEUE_URL"),
                    _job("draft", f"draft:{question['id']}", run.creator_id, run.trace_id,
                         {"questionId": question["id"]}))

    db.update_message(origin_id, in_progress, {
        "status": decision["status"], "category": decision["category"], "confidence": decision["confidence"],
        "reason": decision["reason"], "model": decision["model"], "service_kind": decision["service_kind"],
        "prompt_version": decision["prompt_version"]})


def _triage_path(run):
    """Triage the claimed message as a new DM (spec 5.3 steps 2 to 4). Returns its final status."""
    recent = _recent(run, run.message)
    decision = triage.triage(run.message["text"], recent, run.profile)
    _write_decision(run, decision, run.message, "triaging")
    return decision["status"]


def _reassess_path(run):
    """Reassess the claimed original with this reply (spec 5.5 steps 3 to 6). Returns its final status.

    The reply is saved only after reassess succeeds, so a retry after an
    outage still sees the round as open.
    """
    db, message, original = run.db, run.message, run.original
    rounds = [dict(item) for item in run.rounds]
    rounds[-1]["reply"] = message["text"] or ""
    recent = _recent(run, original)
    try:
        decision = triage.reassess(original["text"], rounds, recent, run.profile)
    except ValueError:
        db.update_message(original["id"], "reassessing", {"status": "awaiting_clarification"})
        run.original, run.rounds = None, []
        return _triage_path(run)
    db.save_reply(run.rounds[-1]["id"], message["text"])
    _write_decision(run, decision, original, "reassessing")
    db.update_message(message["id"], "triaging", {"status": "closed_no_action"})
    return decision["status"]


def _decide(run):
    """Run the job after the message has loaded (spec 5.2 to 5.5). Returns (outcome, status)."""
    original, rounds = _open_clarification(run)
    if not _claim_message(run):
        return DONE, "skipped"
    if original and _claim_original(run, original, rounds):
        return DONE, _reassess_path(run)
    return DONE, _triage_path(run)


def _outage(run):
    """Handle an llm.LLMError (spec 5.6). Returns (outcome, status).

    The new attempt count and the reset go in one write, on the origin: the
    original on the reassess path, otherwise the message.
    """
    db, message, original = run.db, run.message, run.original
    origin = original or message
    in_progress = "reassessing" if original else "triaging"
    attempts = (origin.get("triage_attempts") or 0) + 1
    if attempts >= MAX_ATTEMPTS:
        if original:
            db.save_reply(run.rounds[-1]["id"], message["text"])
        db.update_message(origin["id"], in_progress, {
            "status": "creator_decision", "reason": OUTAGE_REASON, "triage_attempts": attempts})
        if original:
            db.update_message(message["id"], "triaging", {"status": "closed_no_action"})
        return DONE, "creator_decision"
    if original:
        db.update_message(message["id"], "triaging", {"status": None})
    db.update_message(origin["id"], in_progress, {
        "status": "awaiting_clarification" if original else None, "triage_attempts": attempts})
    return RETRY, "retry_pending"


def _reset(run):
    """Put claimed messages back, best effort, keeping triage_attempts (spec 5.6)."""
    try:
        if run.original:
            run.db.update_message(run.original["id"], "reassessing", {"status": "awaiting_clarification"})
        if run.claimed:
            run.db.update_message(run.message["id"], "triaging", {"status": None})
    except Exception as error:
        logger.warning("AI worker stage=reset FAIL message_id=%s error_type=%s", run.message["id"],
                       type(error).__name__)


def _triage_job(job, receive_count, db, publish):
    """Run one triage or reassess job (spec section 5).

    Args:
        job (dict): The job envelope.
        receive_count (int): SQS ApproximateReceiveCount.
        db (Db): The database client.
        publish (callable[[str, dict], None]): Sends a job to a queue URL.

    Returns:
        tuple[str, str]: (outcome, status). outcome is DONE or RETRY. status
        is the final status, for the log.

    Side effects: database writes, model calls and published jobs.
    """
    message_id = job["payload"]["messageId"]
    run = None
    try:
        message = db.get_message(message_id)
        if not message:
            logger.warning("AI worker stage=load message_missing message_id=%s", message_id)
            return DONE, "missing"
        follower = db.get_follower(message["follower_id"])
        if not follower:
            logger.warning("AI worker stage=load follower_missing message_id=%s", message_id)
            return DONE, "missing"
        if follower["creator_id"] != job.get("creatorId"):
            logger.warning("AI worker stage=load creator_mismatch message_id=%s", message_id)
        run = _TriageRun(db, publish, message, follower, job.get("traceId"), receive_count)
        try:
            return _decide(run)
        except llm.LLMError as error:
            logger.warning("AI worker stage=triage FAIL message_id=%s error_type=LLMError service=%s status=%s code=%s",
                           message_id, error.service, error.status or "network", error.code or "unknown")
            return _outage(run)
    except RuntimeError as error:
        logger.error("AI worker config_error message_id=%s error_type=%s", message_id, type(error).__name__)
    except Exception as error:
        logger.error("AI worker stage=triage FAIL message_id=%s error_type=%s", message_id, type(error).__name__)
    if run:
        _reset(run)
    return RETRY, "retry_pending"


def _draft_row(question_id, decision):
    """Build the drafts row for a draft() decision (spec 6 step 4)."""
    answer = decision["draft"]
    return {"question_id": question_id, "status": "ready" if decision["status"] == "drafted" else "no_draft",
            "ai_text": answer["ai_text"] if answer else None, "citations": answer["citations"] if answer else [],
            "used_web_search": False, "model_used": decision["model"], "prompt_version": decision["prompt_version"],
            "knowledge_coverage": decision["knowledge_coverage"], "missing_info": decision["missing_info"],
            "reason": None if answer else decision["reason"]}


def _write_draft(db, question_id, decision):
    """Save a draft() decision and hand the question to the creator (spec 6 steps 4 to 6).

    An existing drafts row is reused, but its flags are still written: a job
    that died right after the insert must not lose its checkpoint-2 flags.

    Args:
        db (Db): The database client.
        question_id (str): The question.
        decision (dict): The decision from draft().

    Returns:
        None

    Side effects: database writes.
    """
    row = db.find_draft(question_id) or db.insert_draft(_draft_row(question_id, decision))
    if decision["safety_flags"]:
        _insert_missing_flags(db, decision["safety_flags"], "draft", row["id"], "2")
        db.flag_question(question_id)
    db.update_question(question_id, "drafting", "awaiting_creator")


def _run_draft(question, receive_count, db, time_left):
    """Run draft() for a claimed question and save the result. Returns (outcome, status)."""
    question_id, origin_id = question["id"], question["origin_message_id"]
    creator_id = question["creator_id"]
    original_text, rounds, topics = None, [], []
    if origin_id:
        original_text = db.get_message_text(origin_id)
        rounds = db.get_rounds(origin_id)
        topics = db.risk_topics(origin_id)
    try:
        decision = draft.draft(question["question_text"], creator_id=creator_id, rounds=rounds,
                               original_text=original_text, channel=question["source"],
                               safety_flagged=question["safety_flagged"], flagged_topics=topics,
                               profile=prompts.profile_for(creator_id),
                               time_left=time_left() - DRAFT_WRITE_RESERVE)
    except ValueError:
        logger.warning("AI worker bad_channel question_id=%s", question_id)
        db.update_question(question_id, "drafting", "awaiting_creator")
        return DONE, "awaiting_creator"
    except llm.LLMError as error:
        logger.warning("AI worker stage=draft FAIL question_id=%s error_type=LLMError service=%s status=%s code=%s",
                       question_id, error.service, error.status or "network", error.code or "unknown")
        if receive_count >= MAX_ATTEMPTS:
            logger.warning("AI worker draft_unavailable question_id=%s", question_id)
            db.update_question(question_id, "drafting", "awaiting_creator")
            return DONE, "awaiting_creator"
        db.update_question(question_id, "drafting", "paid")
        return RETRY, "paid"
    _write_draft(db, question_id, decision)
    return DONE, "awaiting_creator"


def _draft_job(job, receive_count, db, time_left):
    """Run one draft job (spec section 6).

    Args:
        job (dict): The job envelope.
        receive_count (int): SQS ApproximateReceiveCount.
        db (Db): The database client.
        time_left (callable[[], float]): Seconds left in the Lambda.

    Returns:
        tuple[str, str]: (outcome, status). outcome is DONE or RETRY. status
        is the question's status, for the log.

    Side effects: database writes and model calls.
    """
    question_id = job["payload"]["questionId"]
    claimed = False
    try:
        statuses = ("paid", "drafting") if receive_count > 1 else ("paid",)
        question = db.claim_question(question_id, statuses)
        if not question:
            return DONE, "skipped"
        claimed = True
        return _run_draft(question, receive_count, db, time_left)
    except RuntimeError as error:
        logger.error("AI worker config_error question_id=%s error_type=%s", question_id, type(error).__name__)
    except Exception as error:
        logger.error("AI worker stage=draft FAIL question_id=%s error_type=%s", question_id, type(error).__name__)
    if claimed:
        try:
            db.update_question(question_id, "drafting", "paid")
        except Exception as error:
            logger.warning("AI worker stage=reset FAIL question_id=%s error_type=%s", question_id,
                           type(error).__name__)
    return RETRY, "retry_pending"


def run_job(job, *, receive_count, db, publish, time_left):
    """Run one validated job. Never raises.

    Args:
        job (dict): A job from parse_job.
        receive_count (int): SQS ApproximateReceiveCount.
        db (Db): The database client.
        publish (callable[[str, dict], None]): Sends a job to a queue URL.
        time_left (callable[[], float]): Seconds left in the Lambda.

    Returns:
        str: "done" to acknowledge the job, "retry" to have SQS redeliver it.

    Side effects: database writes, model calls, published jobs and one log
    line per job (ids, outcome, status and latency only).
    """
    started = time.monotonic()
    if job["type"] == "draft":
        outcome, status = _draft_job(job, receive_count, db, time_left)
    else:
        outcome, status = _triage_job(job, receive_count, db, publish)
    logger.info("AI worker job=%s id=%s trace=%s outcome=%s status=%s latency_ms=%d", job["type"], job.get("id"),
                job.get("traceId"), outcome, status, int((time.monotonic() - started) * 1000))
    return outcome
