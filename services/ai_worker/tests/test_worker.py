"""Unit tests for worker.py and db.py.

No test calls a real model, database or queue. FakeDb keeps in-memory tables
behind Db.request, with the PostgREST filters the worker uses, so the real
queries in db.py run. triage.triage, triage.reassess and draft.draft are
patched. Every fixture uses made-up text. Case numbers match spec section 11.
Run with:
    python3.11 -m unittest discover -s services/ai_worker/tests
"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import Db, DbError  # noqa: E402  (needs the sys.path line above)
import knowledge  # noqa: E402
import llm  # noqa: E402
import handler  # noqa: E402
import worker  # noqa: E402


CREATOR = "c0000000-0000-4000-8000-000000000001"
FOLLOWER = "f0000000-0000-4000-8000-000000000001"
MESSAGE = "a0000000-0000-4000-8000-000000000001"
REPLY = "a0000000-0000-4000-8000-000000000002"
AI_QUEUE = "https://sqs.test/ai-jobs"
OUTBOUND_QUEUE = "https://sqs.test/outbound"
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

# Every private text carries PRIVATE, so WorkerCase.tearDown can search the logs for it.
DM_TEXT = "PRIVATE-DM my made-up fern has pale fronds"
REPLY_TEXT = "PRIVATE-REPLY north window, weekly watering"
PROMPT_TEXT = "PRIVATE-PROMPT which plant is it"
DECLINE_TEXT = "PRIVATE-DECLINE sorry, I can't help with that"
REASON_TEXT = "PRIVATE-REASON asks about pale fronds"
ANSWER_TEXT = "PRIVATE-ANSWER give it more light"
PRIVATE = "PRIVATE-"

COLUMN_DEFAULTS = {
    "inbound_messages": {"status": None, "triage_attempts": 0, "category": None, "confidence": None, "reason": None,
                         "model": None, "service_kind": None, "prompt_version": None},
    "questions": {"safety_flagged": False, "paid_at": None},
    "clarification_rounds": {"reply": None},
}


class Crash(BaseException):
    """A Lambda dying midway: not an Exception, so no worker handler can catch it."""


def iso(moment):
    return moment.isoformat()


def _matches(row, column, operator, value):
    """Apply one PostgREST filter to one row."""
    current = row.get(column)
    if operator == "is":
        return current is None
    if operator == "in":
        return current is not None and str(current) in value.strip("()").split(",")
    if current is None:
        return False
    if operator == "eq":
        return str(current) == value
    if operator == "neq":
        return str(current) != value
    left, right = datetime.fromisoformat(current), datetime.fromisoformat(value)
    return left < right if operator == "lt" else left >= right


def dict_pairs(params):
    """Return query parameters as pairs, from a dict or a list of pairs."""
    return list(params.items()) if isinstance(params, dict) else list(params or [])


def _logic(row, text, combine):
    """Apply an or=(...) or and=(...) filter. Values here never hold a comma."""
    tests = []
    for part in text[1:-1].split(","):
        column, operator, value = part.split(".", 2)
        tests.append(_matches(row, column, operator, value))
    return combine(tests)


class FakeDb(Db):
    """In-memory tables behind Db.request. The query methods are the real ones."""

    def __init__(self):
        self.tables = {name: [] for name in ("inbound_messages", "ig_followers", "clarification_rounds", "questions",
                                             "drafts", "outbound_messages", "safety_flags")}
        self.tables["ig_followers"].append({"id": FOLLOWER, "creator_id": CREATOR, "ig_scoped_id": "1001"})
        self.writes = []
        self.crash_on = None      # (method, table) raises Crash before that write
        self.fail_on = None       # (method, table) raises DbError before that write

    def add_message(self, message_id=MESSAGE, *, text=DM_TEXT, status=None, received_at=NOW, attempts=0,
                    category=None):
        row = {**COLUMN_DEFAULTS["inbound_messages"], "id": message_id, "follower_id": FOLLOWER, "text": text,
               "status": status, "category": category, "received_at": iso(received_at), "triage_attempts": attempts}
        self.tables["inbound_messages"].append(row)
        return row

    def add_round(self, message_id=MESSAGE, *, round_=1, prompt=PROMPT_TEXT, reply=None):
        row = {"id": str(uuid.uuid4()), "message_id": message_id, "round": round_, "prompt": prompt, "reply": reply}
        self.tables["clarification_rounds"].append(row)
        return row

    def row(self, table, row_id):
        return next(row for row in self.tables[table] if row["id"] == row_id)

    def _filtered(self, table, params):
        rows = self.tables[table]
        for key, value in dict_pairs(params):
            if key in ("select", "order", "limit"):
                continue
            if key == "or":
                rows = [row for row in rows if _logic(row, value, any)]
            elif key == "and":
                rows = [row for row in rows if _logic(row, value, all)]
            else:
                operator, _, operand = value.partition(".")
                rows = [row for row in rows if _matches(row, key, operator, operand)]
        return rows

    @staticmethod
    def _shaped(rows, params):
        rows, options = list(rows), dict(dict_pairs(params))
        if "order" in options:
            column, _, direction = options["order"].partition(".")
            rows.sort(key=lambda row: row[column], reverse=direction == "desc")
        if "limit" in options:
            rows = rows[:int(options["limit"])]
        if "select" in options:
            columns = options["select"].split(",")
            return [{column: row.get(column) for column in columns} for row in rows]
        return [dict(row) for row in rows]

    def _insert_rows(self, table, body):
        created = []
        for item in body if isinstance(body, list) else [body]:
            row = {"id": str(uuid.uuid4()), **COLUMN_DEFAULTS.get(table, {}), **item}
            key = row.get("client_request_id")
            if key and any(other.get("client_request_id") == key for other in self.tables[table]):
                raise DbError(409, "23505")
            self.tables[table].append(row)
            created.append(row)
        return created

    def request(self, method, path, *, params=None, body=None, prefer=None):
        if method != "GET":
            if self.crash_on == (method, path):
                raise Crash()
            if self.fail_on == (method, path):
                raise DbError(500, "XX000")
        if method == "GET":
            return self._shaped(self._filtered(path, params), params)
        if method == "POST":
            created = self._insert_rows(path, body)
            self.writes.append((method, path, body))
            return self._shaped(created, None) if prefer else None
        rows = self._filtered(path, params)
        for row in rows:
            row.update(body)
            self.writes.append((method, path, body))
        return self._shaped(rows, params) if prefer else None


class FakePublisher:
    """Records every published job."""

    def __init__(self):
        self.jobs = []

    def __call__(self, queue_url, job):
        self.jobs.append((queue_url, job))

    def of_type(self, job_type):
        return [job for _, job in self.jobs if job["type"] == job_type]


def decision(status="ready_for_question", **fields):
    """A triage decision with sensible defaults."""
    base = {"status": status, "category": "expert_question", "service_kind": None, "confidence": 0.94,
            "reason": REASON_TEXT, "prompt_version": "triage-v4+sweetlife-v2", "model": "test-model",
            "safety_flags": [], "question": None, "clarification": None, "outbound": None}
    return {**base, **fields}


def ready(**fields):
    return decision(question={"question_text": DM_TEXT, "safety_flagged": False}, **fields)


def vague(round_=1):
    return decision("awaiting_clarification", category="needs_clarification",
                    clarification={"round": round_, "prompt": PROMPT_TEXT},
                    outbound={"type": "clarification", "text": PROMPT_TEXT})


def blocked():
    return decision("blocked", category="safety_concern", confidence=None,
                    safety_flags=[{"layer": "moderation", "category": "harassment", "detail": None},
                                  {"layer": "rules", "category": "blocked_term", "detail": None}],
                    outbound={"type": "decline", "text": DECLINE_TEXT})


def drafted(**fields):
    base = {"status": "drafted", "reason": None,
            "draft": {"ai_text": ANSWER_TEXT, "citations": [{"kind": "knowledge", "ref": "k1", "title": "Guide > Light",
                                                             "hpa_id": "HPA-FUND-0001", "supports": "light"}],
                      "used_web_search": False},
            "knowledge_coverage": "high", "missing_info": [], "safety_flags": [], "model": "test-draft-model",
            "prompt_version": "draft-v3+sweetlife-v2", "retrieved": [{"entry_id": "k1"}]}
    return {**base, **fields}


def no_draft():
    return {"status": "no_draft", "reason": "no_coverage", "draft": None, "knowledge_coverage": "none",
            "missing_info": ["toxicity to pets"], "safety_flags": [], "model": None,
            "prompt_version": "draft-v3+sweetlife-v2", "retrieved": []}


def triage_job(message_id=MESSAGE):
    return {"v": 1, "type": "triage", "id": f"triage:{message_id}", "creatorId": CREATOR, "traceId": "trace-1",
            "createdAt": iso(NOW), "payload": {"messageId": message_id}}


def draft_job(question_id):
    return {"v": 1, "type": "draft", "id": f"draft:{question_id}", "creatorId": CREATOR, "traceId": "trace-1",
            "createdAt": iso(NOW), "payload": {"questionId": question_id}}


class WorkerCase(unittest.TestCase):
    """Sets up the fakes, and checks after every test that logs hold no private text (case 19)."""

    stub = "true"

    def setUp(self):
        self.db = FakeDb()
        self.publish = FakePublisher()
        self.env = patch.dict(os.environ, {"PAYMENT_STUB": self.stub, "AI_JOBS_QUEUE_URL": AI_QUEUE,
                                           "OUTBOUND_QUEUE_URL": OUTBOUND_QUEUE})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.triage = self._patch("triage.triage", return_value=ready())
        self.reassess = self._patch("triage.reassess", return_value=ready())
        self.draft = self._patch("draft.draft", return_value=drafted())
        self.logs = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda record: self.logs.append(record.getMessage())
        for name in ("worker", "handler"):
            logging.getLogger(name).addHandler(handler)
            self.addCleanup(logging.getLogger(name).removeHandler, handler)

    def tearDown(self):
        self.assertTrue(self.logs, "a job always logs")
        self.assertFalse([line for line in self.logs if PRIVATE in line])

    def _patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def run_job(self, job=None, receive_count=1):
        return worker.run_job(job or triage_job(), receive_count=receive_count, db=self.db, publish=self.publish,
                              time_left=lambda: 100)

    def message(self, message_id=MESSAGE):
        return self.db.row("inbound_messages", message_id)

    def question(self):
        self.assertEqual(len(self.db.tables["questions"]), 1)
        return self.db.tables["questions"][0]

    def claimed_question(self, *, status="paid", flagged=False):
        row = {"id": str(uuid.uuid4()), "creator_id": CREATOR, "source": "instagram", "follower_id": FOLLOWER,
               "origin_message_id": MESSAGE, "question_text": DM_TEXT, "status": status, "safety_flagged": flagged,
               "paid_at": iso(NOW)}
        self.db.tables["questions"].append(row)
        return row["id"]


class TriageTests(WorkerCase):
    def test_01_clear_question_with_stub(self):
        self.db.add_message()
        self.assertEqual(self.run_job(), "done")
        message, question = self.message(), self.question()
        self.assertEqual(message["status"], "ready_for_question")
        self.assertEqual((message["category"], message["confidence"], message["reason"], message["model"],
                          message["prompt_version"]),
                         ("expert_question", 0.94, REASON_TEXT, "test-model", "triage-v4+sweetlife-v2"))
        self.assertEqual((question["status"], question["source"], question["origin_message_id"],
                          question["creator_id"], question["follower_id"]),
                         ("paid", "instagram", MESSAGE, CREATOR, FOLLOWER))
        self.assertIsNotNone(question["paid_at"])
        self.assertEqual(self.db.tables["outbound_messages"], [])
        self.assertEqual(len(self.publish.jobs), 1)
        queue, job = self.publish.jobs[0]
        self.assertEqual(queue, AI_QUEUE)
        self.assertEqual((job["v"], job["type"], job["id"], job["creatorId"], job["traceId"], job["payload"]),
                         (1, "draft", f"draft:{question['id']}", CREATOR, "trace-1", {"questionId": question["id"]}))

    def test_02_same_job_twice_does_nothing_the_second_time(self):
        self.db.add_message()
        self.run_job()
        writes, published = len(self.db.writes), len(self.publish.jobs)
        self.assertEqual(self.run_job(), "done")
        self.assertEqual(len(self.db.writes), writes)
        self.assertEqual(len(self.publish.jobs), published)
        self.assertEqual(self.triage.call_count, 1)
        self.question()

    def test_03_crash_before_final_status_is_finished_without_duplicates(self):
        self.db.add_message()
        flags = [{"layer": "policy", "category": "risk_topic", "detail": "pesticides or chemical use"}]
        self.triage.return_value = ready(safety_flags=flags)
        real_update = self.db.update_message

        def crash_on_final(*args):
            raise Crash()

        self.db.update_message = crash_on_final
        with self.assertRaises(Crash):
            self.run_job()
        self.db.update_message = real_update
        self.assertEqual(self.message()["status"], "triaging")

        self.assertEqual(self.run_job(receive_count=2), "done")
        self.assertEqual(self.message()["status"], "ready_for_question")
        self.question()
        self.assertEqual(len(self.db.tables["safety_flags"]), 1)

    def test_03_crash_with_clarification_leaves_one_round_and_one_outbound(self):
        self.db.add_message()
        self.triage.return_value = vague()
        real_update = self.db.update_message

        def crash_on_final(*args):
            raise Crash()

        self.db.update_message = crash_on_final
        with self.assertRaises(Crash):
            self.run_job()
        self.db.update_message = real_update
        self.run_job(receive_count=2)
        self.assertEqual(len(self.db.tables["clarification_rounds"]), 1)
        self.assertEqual(len(self.db.tables["outbound_messages"]), 1)
        self.assertEqual(self.message()["status"], "awaiting_clarification")

    def test_triaging_message_is_not_taken_on_first_delivery(self):
        self.db.add_message(status="triaging")
        self.assertEqual(self.run_job(), "done")
        self.assertEqual(self.triage.call_count, 0)

    def test_04_vague_dm(self):
        self.db.add_message()
        self.triage.return_value = vague()
        self.assertEqual(self.run_job(), "done")
        self.assertEqual(self.message()["status"], "awaiting_clarification")
        round_row = self.db.tables["clarification_rounds"][0]
        self.assertEqual((round_row["message_id"], round_row["round"], round_row["prompt"], round_row["reply"]),
                         (MESSAGE, 1, PROMPT_TEXT, None))
        outbound = self.db.tables["outbound_messages"][0]
        self.assertEqual((outbound["type"], outbound["text"], outbound["status"], outbound["attempts"],
                          outbound["delivery_mode"], outbound["inbound_message_id"], outbound["follower_id"],
                          outbound["creator_id"], outbound["draft_id"]),
                         ("clarification", PROMPT_TEXT, "pending", 0, "standard", MESSAGE, FOLLOWER, CREATOR, None))
        self.assertEqual(outbound["client_request_id"],
                         str(uuid.uuid5(worker.OUTBOUND_NS, f"{MESSAGE}:clarification:1")))
        queue, job = self.publish.jobs[0]
        self.assertEqual(queue, OUTBOUND_QUEUE)
        self.assertEqual((job["type"], job["id"], job["payload"]),
                         ("clarification", f"outbound:{outbound['id']}", {"outboundMessageId": outbound["id"]}))
        self.assertEqual(self.db.tables["questions"], [])

    def test_outbound_row_already_there_is_reused(self):
        self.db.add_message()
        self.triage.return_value = vague()
        request_id = str(uuid.uuid5(worker.OUTBOUND_NS, f"{MESSAGE}:clarification:1"))
        self.db.tables["outbound_messages"].append({"id": "existing", "client_request_id": request_id})
        self.assertEqual(self.run_job(), "done")
        self.assertEqual(len(self.db.tables["outbound_messages"]), 1)
        self.assertEqual(self.publish.jobs[0][1]["payload"], {"outboundMessageId": "existing"})

    def test_07_blocked_dm(self):
        self.db.add_message()
        self.triage.return_value = blocked()
        self.assertEqual(self.run_job(), "done")
        self.assertEqual(self.message()["status"], "blocked")
        flags = self.db.tables["safety_flags"]
        self.assertEqual(len(flags), 2)
        for flag in flags:
            self.assertEqual((flag["target_type"], flag["target_id"], flag["checkpoint"]), ("message", MESSAGE, "1"))
        outbound = self.db.tables["outbound_messages"][0]
        self.assertEqual((outbound["type"], outbound["client_request_id"]),
                         ("decline", str(uuid.uuid5(worker.OUTBOUND_NS, f"{MESSAGE}:decline:0"))))
        self.assertEqual(self.db.tables["questions"], [])

    def test_only_missing_flags_are_inserted(self):
        self.db.add_message()
        self.db.tables["safety_flags"].append({
            "id": "old", "target_type": "message", "target_id": MESSAGE, "checkpoint": "1", "layer": "moderation",
            "category": "harassment", "detail": None})
        self.triage.return_value = blocked()
        self.run_job()
        self.assertEqual(len(self.db.tables["safety_flags"]), 2)

    def test_empty_text_dm_reaches_triage_as_none(self):
        self.db.add_message(text=None)
        self.triage.return_value = vague()
        self.assertEqual(self.run_job(), "done")
        self.assertIsNone(self.triage.call_args.args[0])

    def test_reassess_job_type_runs_like_triage(self):
        self.db.add_message()
        job = {**triage_job(), "type": "reassess", "id": f"reassess:{MESSAGE}"}
        self.assertEqual(self.run_job(job), "done")
        self.assertEqual(self.message()["status"], "ready_for_question")

    def test_missing_message_is_acknowledged(self):
        self.assertEqual(self.run_job(), "done")
        self.assertEqual(self.db.writes, [])

    def test_creator_mismatch_uses_the_followers_creator(self):
        self.db.add_message()
        self.assertEqual(self.run_job({**triage_job(), "creatorId": "someone-else"}), "done")
        self.assertEqual(self.question()["creator_id"], CREATOR)
        self.assertTrue(any("creator_mismatch" in line for line in self.logs))

    def test_09_llm_error_on_attempts_1_and_2(self):
        self.db.add_message()
        self.triage.side_effect = llm.LLMError("openrouter", 503, "unavailable")
        for attempt in (1, 2):
            self.assertEqual(self.run_job(receive_count=attempt), "retry")
            self.assertIsNone(self.message()["status"])
            self.assertEqual(self.message()["triage_attempts"], attempt)

    def test_10_llm_error_on_attempt_3(self):
        self.db.add_message(attempts=2)
        self.triage.side_effect = llm.LLMError("openrouter", 503, "unavailable")
        self.assertEqual(self.run_job(receive_count=3), "done")
        self.assertEqual(self.message()["status"], "creator_decision")
        self.assertEqual(self.message()["reason"], worker.OUTAGE_REASON)
        self.assertEqual(self.message()["triage_attempts"], 3)

    def test_db_error_resets_without_counting_an_attempt(self):
        self.db.add_message()
        self.db.fail_on = ("POST", "questions")
        self.assertEqual(self.run_job(), "retry")
        self.assertIsNone(self.message()["status"])
        self.assertEqual(self.message()["triage_attempts"], 0)

    def test_runtime_error_is_a_config_error_and_retries(self):
        self.db.add_message()
        self.triage.side_effect = RuntimeError("Missing OPENAI_API_KEY")
        self.assertEqual(self.run_job(), "retry")
        self.assertIsNone(self.message()["status"])
        self.assertTrue(any("config_error" in line for line in self.logs))

    def test_unexpected_error_resets_and_retries(self):
        self.db.add_message()
        self.triage.side_effect = KeyError("surprise")
        self.assertEqual(self.run_job(), "retry")
        self.assertIsNone(self.message()["status"])

    def test_11_recent_messages(self):
        self.db.add_message(received_at=NOW)
        minutes = lambda n: NOW - timedelta(minutes=n)  # noqa: E731
        self.db.add_message("m-old", text="too old", received_at=minutes(31))
        self.db.add_message("m-second", text="second", received_at=minutes(5), status="ready_for_question")
        self.db.add_message("m-first", text="first", received_at=minutes(20))
        self.db.add_message("m-blocked", text="blocked one", received_at=minutes(6), status="blocked")
        self.db.add_message("m-closed", text="closed one", received_at=minutes(7), status="closed_no_action")
        self.db.add_message("m-empty", text="   ", received_at=minutes(8))
        self.db.add_message("m-none", text=None, received_at=minutes(9))
        self.db.add_message("m-flagged", text="flagged one", received_at=minutes(10), status="creator_decision",
                            category="safety_concern")
        self.db.add_message("m-later", text="later", received_at=NOW + timedelta(minutes=1))
        self.run_job()
        self.assertEqual(self.triage.call_args.args[:2], (DM_TEXT, ["first", "second"]))
        self.assertNotIn("flagged one", self.triage.call_args.args[1])


class StubOffTests(WorkerCase):
    stub = "false"

    def test_08_stub_off(self):
        self.db.add_message()
        self.assertEqual(self.run_job(), "done")
        self.assertEqual(self.question()["status"], "pending_payment")
        self.assertIsNone(self.question()["paid_at"])
        self.assertEqual(self.publish.jobs, [])


class ReassessTests(WorkerCase):
    def setUp(self):
        super().setUp()
        self.db.add_message(status="awaiting_clarification", received_at=NOW - timedelta(minutes=2))
        self.round = self.db.add_round()
        self.db.add_message(REPLY, text=REPLY_TEXT)

    def job(self):
        return triage_job(REPLY)

    def test_05_reply_to_open_clarification(self):
        self.assertEqual(self.run_job(self.job()), "done")
        self.assertEqual(self.message()["status"], "ready_for_question")
        self.assertEqual(self.round["reply"], REPLY_TEXT)
        self.assertEqual(self.message(REPLY)["status"], "closed_no_action")
        self.assertEqual(self.question()["origin_message_id"], MESSAGE)
        self.assertEqual(self.triage.call_count, 0)
        args = self.reassess.call_args.args
        self.assertEqual(args[0], DM_TEXT)
        self.assertEqual(args[1][0]["reply"], REPLY_TEXT)

    def test_round_2_is_asked_on_the_original(self):
        self.reassess.return_value = vague(round_=2)
        self.assertEqual(self.run_job(self.job()), "done")
        self.assertEqual(self.message()["status"], "awaiting_clarification")
        rounds = self.db.tables["clarification_rounds"]
        self.assertEqual([(row["message_id"], row["round"]) for row in rounds], [(MESSAGE, 1), (MESSAGE, 2)])
        self.assertEqual(self.db.tables["outbound_messages"][0]["inbound_message_id"], MESSAGE)
        self.assertEqual(self.message(REPLY)["status"], "closed_no_action")

    def test_reply_already_closed_is_acknowledged(self):
        self.reassess.return_value = vague(round_=2)
        self.run_job(self.job())
        self.assertEqual(self.run_job(self.job()), "done")
        self.assertEqual(self.reassess.call_count, 1)

    def test_06_original_no_longer_awaiting(self):
        self.message()["status"] = "creator_decision"
        self.assertEqual(self.run_job(self.job()), "done")
        self.assertEqual(self.reassess.call_count, 0)
        self.assertEqual(self.triage.call_count, 1)
        self.assertEqual(self.message(REPLY)["status"], "ready_for_question")

    def test_06_original_claimed_by_another_run_between_read_and_claim(self):
        real = self.db.update_message_where

        def taken(message_id, statuses, values):
            return None if values == {"status": "reassessing"} else real(message_id, statuses, values)

        self.db.update_message_where = taken
        self.assertEqual(self.run_job(self.job()), "done")
        self.assertEqual(self.triage.call_count, 1)
        self.assertEqual(self.message(REPLY)["status"], "ready_for_question")

    def test_answered_round_means_a_new_message(self):
        self.round["reply"] = "an earlier reply"
        self.assertEqual(self.run_job(self.job()), "done")
        self.assertEqual(self.triage.call_count, 1)

    def test_reply_is_not_saved_on_llm_error(self):
        self.reassess.side_effect = llm.LLMError("openrouter", None, "timeout")
        self.assertEqual(self.run_job(self.job()), "retry")
        self.assertIsNone(self.round["reply"])
        self.assertEqual(self.message()["status"], "awaiting_clarification")
        self.assertEqual(self.message()["triage_attempts"], 1)
        self.assertIsNone(self.message(REPLY)["status"])
        self.assertEqual(self.message(REPLY)["triage_attempts"], 0)

    def test_retry_after_llm_error_finishes_the_reassess(self):
        self.reassess.side_effect = llm.LLMError("openrouter", None, "timeout")
        self.run_job(self.job())
        self.reassess.side_effect = None
        self.assertEqual(self.run_job(self.job(), receive_count=2), "done")
        self.assertEqual(self.message()["status"], "ready_for_question")
        self.assertEqual(self.message(REPLY)["status"], "closed_no_action")

    def test_third_llm_error_goes_to_the_creator(self):
        self.message()["triage_attempts"] = 2
        self.reassess.side_effect = llm.LLMError("openrouter", None, "timeout")
        self.assertEqual(self.run_job(self.job(), receive_count=3), "done")
        self.assertEqual(self.message()["status"], "creator_decision")
        self.assertEqual(self.message()["reason"], worker.OUTAGE_REASON)
        self.assertEqual(self.round["reply"], REPLY_TEXT)
        self.assertEqual(self.message(REPLY)["status"], "closed_no_action")

    def test_value_error_from_reassess_falls_back_to_triage(self):
        self.reassess.side_effect = ValueError("reassess needs at least one clarification round")
        self.assertEqual(self.run_job(self.job()), "done")
        self.assertEqual(self.message()["status"], "awaiting_clarification")
        self.assertEqual(self.message(REPLY)["status"], "ready_for_question")

    def test_crash_mid_reassess_is_finished_by_the_redelivery(self):
        self.reassess.side_effect = Crash()
        with self.assertRaises(Crash):
            self.run_job(self.job())
        self.assertEqual(self.message()["status"], "reassessing")
        self.reassess.side_effect = None
        self.assertEqual(self.run_job(self.job(), receive_count=2), "done")
        self.assertEqual(self.triage.call_count, 0)
        self.assertEqual(self.message()["status"], "ready_for_question")
        self.assertEqual(self.round["reply"], REPLY_TEXT)
        self.assertEqual(self.message(REPLY)["status"], "closed_no_action")
        self.question()

    def test_crash_after_saving_the_reply_is_finished_by_the_redelivery(self):
        self.db.crash_on = ("POST", "questions")
        with self.assertRaises(Crash):
            self.run_job(self.job())
        self.assertEqual(self.round["reply"], REPLY_TEXT)
        self.db.crash_on = None
        self.assertEqual(self.run_job(self.job(), receive_count=2), "done")
        self.assertEqual(self.triage.call_count, 0)
        self.assertEqual(self.message()["status"], "ready_for_question")
        self.assertEqual(self.message(REPLY)["status"], "closed_no_action")
        self.question()

    def test_redelivery_finishes_a_reassessing_original_whose_saved_reply_differs(self):
        self.message()["status"] = "reassessing"
        self.message(REPLY)["status"] = "triaging"
        self.round["reply"] = "PRIVATE-EARLIER reply saved before the crash"
        self.assertEqual(self.run_job(self.job(), receive_count=2), "done")
        self.assertEqual(self.triage.call_count, 0)
        self.assertEqual(self.reassess.call_count, 1)
        self.assertEqual(self.message()["status"], "ready_for_question")
        self.assertEqual(self.message(REPLY)["status"], "closed_no_action")
        self.assertEqual(self.round["reply"], "PRIVATE-EARLIER reply saved before the crash")

    def test_redelivery_does_not_take_a_round_answered_by_another_message(self):
        self.round["reply"] = "an earlier reply"
        self.assertEqual(self.run_job(self.job(), receive_count=2), "done")
        self.assertEqual(self.reassess.call_count, 0)
        self.assertEqual(self.triage.call_count, 1)

    def test_retry_after_db_error_with_the_reply_saved_finishes_the_reassess(self):
        self.db.fail_on = ("POST", "questions")
        self.assertEqual(self.run_job(self.job()), "retry")
        self.assertEqual(self.round["reply"], REPLY_TEXT)
        self.assertEqual(self.message()["status"], "awaiting_clarification")
        self.db.fail_on = None
        self.assertEqual(self.run_job(self.job(), receive_count=2), "done")
        self.assertEqual(self.triage.call_count, 0)
        self.assertEqual(self.message()["status"], "ready_for_question")

    def test_first_delivery_never_takes_an_original_in_reassessing(self):
        self.message()["status"] = "reassessing"
        self.assertEqual(self.run_job(self.job()), "done")
        self.assertEqual(self.reassess.call_count, 0)
        self.assertEqual(self.triage.call_count, 1)


class DraftTests(WorkerCase):
    def setUp(self):
        super().setUp()
        self.db.add_message(status="ready_for_question")

    def drafts(self):
        return self.db.tables["drafts"]

    def test_12_drafted(self):
        question_id = self.claimed_question()
        flags = [{"layer": "policy", "category": "risk_topic", "detail": "pesticides or chemical use"}]
        self.draft.return_value = drafted(safety_flags=flags, missing_info=["soil mix"])
        self.assertEqual(self.run_job(draft_job(question_id)), "done")
        row = self.drafts()[0]
        self.assertEqual((row["question_id"], row["status"], row["ai_text"], row["used_web_search"], row["model_used"],
                          row["prompt_version"], row["knowledge_coverage"], row["missing_info"], row["reason"]),
                         (question_id, "ready", ANSWER_TEXT, False, "test-draft-model", "draft-v3+sweetlife-v2",
                          "high", ["soil mix"], None))
        self.assertEqual(row["citations"][0]["ref"], "k1")
        self.assertNotIn("retrieved", row)
        flag = self.db.tables["safety_flags"][0]
        self.assertEqual((flag["target_type"], flag["target_id"], flag["checkpoint"], flag["detail"]),
                         ("draft", row["id"], "2", "pesticides or chemical use"))
        question = self.question()
        self.assertTrue(question["safety_flagged"])
        self.assertEqual(question["status"], "awaiting_creator")

    def test_12_no_flags_leaves_question_unflagged(self):
        question_id = self.claimed_question()
        self.run_job(draft_job(question_id))
        self.assertFalse(self.question()["safety_flagged"])
        self.assertEqual(self.db.tables["safety_flags"], [])

    def test_13_no_draft(self):
        question_id = self.claimed_question()
        self.draft.return_value = no_draft()
        self.assertEqual(self.run_job(draft_job(question_id)), "done")
        row = self.drafts()[0]
        self.assertEqual((row["status"], row["ai_text"], row["citations"], row["reason"], row["missing_info"],
                          row["model_used"]),
                         ("no_draft", None, [], "no_coverage", ["toxicity to pets"], None))
        self.assertEqual(self.question()["status"], "awaiting_creator")

    def test_14_draft_job_twice(self):
        question_id = self.claimed_question()
        self.run_job(draft_job(question_id))
        writes = len(self.db.writes)
        self.assertEqual(self.run_job(draft_job(question_id)), "done")
        self.assertEqual(len(self.db.writes), writes)
        self.assertEqual(len(self.drafts()), 1)
        self.assertEqual(self.draft.call_count, 1)

    def test_15_llm_error_first_delivery(self):
        question_id = self.claimed_question()
        self.draft.side_effect = llm.LLMError("openrouter", 503, "unavailable")
        self.assertEqual(self.run_job(draft_job(question_id)), "retry")
        self.assertEqual(self.question()["status"], "paid")
        self.assertEqual(self.drafts(), [])

    def test_16_llm_error_third_delivery(self):
        question_id = self.claimed_question(status="drafting")
        self.draft.side_effect = llm.LLMError("openrouter", None, "deadline")
        self.assertEqual(self.run_job(draft_job(question_id), receive_count=3), "done")
        self.assertEqual(self.question()["status"], "awaiting_creator")
        self.assertEqual(self.drafts(), [])
        self.assertTrue(any("draft_unavailable" in line for line in self.logs))

    def test_17_flagged_topics(self):
        question_id = self.claimed_question(flagged=True)
        flag = {"target_type": "message", "target_id": MESSAGE, "checkpoint": "1", "layer": "policy",
                "category": "risk_topic", "detail": "pesticides or chemical use"}
        self.db.tables["safety_flags"] += [
            {**flag, "id": "1"}, {**flag, "id": "2", "category": "safety_concern", "detail": "other category"},
            {**flag, "id": "3", "layer": "moderation", "detail": "other layer"},
            {**flag, "id": "4", "target_id": "another-message", "detail": "other message"},
            {**flag, "id": "5", "checkpoint": "2", "detail": "other checkpoint"},
            {**flag, "id": "6", "detail": None}]
        self.run_job(draft_job(question_id))
        self.assertEqual(self.draft.call_args.kwargs["flagged_topics"], ["pesticides or chemical use"])

    def test_draft_gets_its_inputs(self):
        question_id = self.claimed_question(flagged=True)
        self.db.add_round(reply=REPLY_TEXT)
        self.run_job(draft_job(question_id))
        args, kwargs = self.draft.call_args
        self.assertEqual(args, (DM_TEXT,))
        self.assertEqual((kwargs["creator_id"], kwargs["original_text"], kwargs["channel"], kwargs["safety_flagged"],
                          kwargs["time_left"]), (CREATOR, DM_TEXT, "instagram", True, 85))
        self.assertEqual(kwargs["rounds"][0]["reply"], REPLY_TEXT)
        self.assertIn("risk_topics", kwargs["profile"])

    def test_unknown_channel(self):
        question_id = self.claimed_question()
        self.draft.side_effect = ValueError("no byte limit")
        self.assertEqual(self.run_job(draft_job(question_id)), "done")
        self.assertEqual(self.question()["status"], "awaiting_creator")
        self.assertEqual(self.drafts(), [])
        self.assertTrue(any("bad_channel" in line for line in self.logs))

    def test_db_error_and_runtime_error_go_back_to_paid(self):
        for error in (DbError(500, "XX000"), RuntimeError("Missing SUPABASE_URL")):
            self.db.tables["questions"].clear()
            question_id = self.claimed_question()
            self.draft.side_effect = error
            self.assertEqual(self.run_job(draft_job(question_id)), "retry")
            self.assertEqual(self.question()["status"], "paid")

    def test_unpaid_or_seed_questions_are_never_touched(self):
        question_id = self.claimed_question(status="delivered")
        self.assertEqual(self.run_job(draft_job(question_id), receive_count=2), "done")
        self.assertEqual(self.question()["status"], "delivered")
        self.assertEqual(self.draft.call_count, 0)

    def test_crash_after_draft_insert_keeps_text_and_flags_from_one_run(self):
        question_id = self.claimed_question()
        first_flags = [{"layer": "policy", "category": "risk_topic", "detail": "first run topic"}]
        self.draft.return_value = drafted(safety_flags=first_flags)
        self.db.crash_on = ("POST", "safety_flags")
        with self.assertRaises(Crash):
            self.run_job(draft_job(question_id))
        self.assertEqual(self.question()["status"], "drafting")
        self.assertEqual(self.drafts()[0]["ai_text"], ANSWER_TEXT)
        self.assertEqual(self.db.tables["safety_flags"], [])

        self.db.crash_on = None
        second_flags = [{"layer": "policy", "category": "risk_topic", "detail": "second run topic"}]
        answer = {"ai_text": "PRIVATE-SECOND answer", "citations": [{"ref": "k2"}], "used_web_search": False}
        self.draft.return_value = drafted(safety_flags=second_flags, draft=answer, knowledge_coverage="partial",
                                          missing_info=["soil mix"], model="fallback-model")
        self.assertEqual(self.run_job(draft_job(question_id), receive_count=2), "done")

        self.assertEqual(len(self.drafts()), 1)
        row = self.drafts()[0]
        self.assertEqual((row["status"], row["ai_text"], row["citations"], row["knowledge_coverage"],
                          row["missing_info"], row["reason"], row["model_used"]),
                         ("ready", "PRIVATE-SECOND answer", [{"ref": "k2"}], "partial", ["soil mix"], None,
                          "fallback-model"))
        self.assertEqual([(flag["detail"], flag["target_id"], flag["checkpoint"])
                          for flag in self.db.tables["safety_flags"]], [("second run topic", row["id"], "2")])
        self.assertTrue(self.question()["safety_flagged"])
        self.assertEqual(self.question()["status"], "awaiting_creator")

    def test_existing_draft_becomes_no_draft_when_the_rerun_has_none(self):
        question_id = self.claimed_question(status="drafting")
        self.db.tables["drafts"].append({"id": "old", "question_id": question_id, "status": "ready",
                                         "ai_text": ANSWER_TEXT, "citations": [{"ref": "k1"}], "reason": None})
        self.draft.return_value = no_draft()
        self.assertEqual(self.run_job(draft_job(question_id), receive_count=2), "done")
        row = self.drafts()[0]
        self.assertEqual((row["status"], row["ai_text"], row["citations"], row["reason"]),
                         ("no_draft", None, [], "no_coverage"))


class ParseJobTests(unittest.TestCase):
    def test_18_invalid_jobs(self):
        logger = logging.getLogger("worker")
        logger.disabled = True
        self.addCleanup(setattr, logger, "disabled", False)
        bodies = [None, "not json", "[]", "5", json.dumps({**triage_job(), "v": 2}),
                  json.dumps({**triage_job(), "type": "embed"}), json.dumps({**triage_job(), "type": ["triage"]}),
                  json.dumps({**triage_job(), "payload": {}}), json.dumps({**triage_job(), "payload": None}),
                  json.dumps({**draft_job("q"), "payload": {"messageId": "m"}})]
        for body in bodies:
            self.assertIsNone(worker.parse_job(body), body)

    def test_valid_jobs(self):
        for job in (triage_job(), {**triage_job(), "type": "reassess"}, draft_job("q")):
            self.assertEqual(worker.parse_job(json.dumps(job)), job)


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DbClientTests(unittest.TestCase):
    def setUp(self):
        self.db = Db("https://project.supabase.test/", "service-key")

    def test_url_must_be_https(self):
        with self.assertRaises(ValueError):
            Db("http://project.supabase.test", "service-key")

    def test_request_encodes_params_and_sends_headers(self):
        with patch("db.urlopen", return_value=FakeResponse(b'[{"id":"1"}]')) as urlopen:
            rows = self.db.request("PATCH", "questions", params={"received_at": "lt.2026-11-01T12:00:00+00:00"},
                                   body={"status": "paid"}, prefer="return=representation")
        self.assertEqual(rows, [{"id": "1"}])
        request, timeout = urlopen.call_args.args[0], urlopen.call_args.kwargs["timeout"]
        parts = urlsplit(request.full_url)
        self.assertEqual(parts.path, "/rest/v1/questions")
        self.assertIn("%2B00%3A00", parts.query)
        self.assertEqual(parse_qs(parts.query)["received_at"], ["lt.2026-11-01T12:00:00+00:00"])
        self.assertEqual(request.get_method(), "PATCH")
        self.assertEqual(json.loads(request.data), {"status": "paid"})
        self.assertEqual(request.get_header("Apikey"), "service-key")
        self.assertEqual(request.get_header("Authorization"), "Bearer service-key")
        self.assertEqual(request.get_header("Prefer"), "return=representation")
        self.assertEqual(timeout, 8)

    def test_empty_response_is_none(self):
        with patch("db.urlopen", return_value=FakeResponse(b"")):
            self.assertIsNone(self.db.request("PATCH", "questions", body={}))

    def test_http_error_keeps_status_and_code_only(self):
        error = HTTPError("url", 409, "conflict", {}, BytesIO(b'{"code":"23505","message":"secret text"}'))
        with patch("db.urlopen", side_effect=error):
            with self.assertRaises(DbError) as caught:
                self.db.request("POST", "outbound_messages", body={})
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "23505"))
        self.assertNotIn("secret", str(caught.exception))

    def test_network_errors_and_bad_json(self):
        for effect in (URLError("down"), TimeoutError()):
            with patch("db.urlopen", side_effect=effect):
                with self.assertRaises(DbError) as caught:
                    self.db.request("GET", "questions")
            self.assertEqual((caught.exception.status, caught.exception.code), (None, "network"))
        with patch("db.urlopen", return_value=FakeResponse(b"<html>")):
            with self.assertRaises(DbError):
                self.db.request("GET", "questions")

    def test_recent_messages_exact_query_string(self):
        with patch("db.urlopen", return_value=FakeResponse(b"[]")) as urlopen:
            run = MagicMock(db=self.db, message={"follower_id": FOLLOWER})
            worker._recent(run, {"id": MESSAGE, "received_at": "2026-11-01T12:00:00.123456+00:00"})
        self.assertEqual(urlopen.call_args.args[0].full_url,
                         "https://project.supabase.test/rest/v1/inbound_messages"
                         f"?follower_id=eq.{FOLLOWER}&id=neq.{MESSAGE}"
                         "&received_at=gte.2026-11-01T11%3A30%3A00.123456Z"
                         "&received_at=lt.2026-11-01T12%3A00%3A00.123456Z"
                         "&select=text%2Cstatus%2Ccategory&order=received_at.asc")

    def test_recent_window_converts_other_offsets_to_utc(self):
        with patch("db.urlopen", return_value=FakeResponse(b"[]")) as urlopen:
            run = MagicMock(db=self.db, message={"follower_id": FOLLOWER})
            worker._recent(run, {"id": MESSAGE, "received_at": "2026-11-01T07:00:00-05:00"})
        url = urlopen.call_args.args[0].full_url
        self.assertIn("received_at=gte.2026-11-01T11%3A30%3A00Z&received_at=lt.2026-11-01T12%3A00%3A00Z", url)
        self.assertNotIn("2B00", url)

    def test_claim_filters(self):
        self.db.request = MagicMock(return_value=[])
        self.db.claim_message(MESSAGE, (None, "received"))
        self.assertEqual(self.db.request.call_args.kwargs["params"],
                         {"id": f"eq.{MESSAGE}", "or": "(status.is.null,status.eq.received)"})
        self.db.update_message(MESSAGE, "triaging", {"status": None})
        self.assertEqual(self.db.request.call_args.kwargs["params"], {"id": f"eq.{MESSAGE}", "status": "eq.triaging"})

    def test_other_insert_errors_are_not_swallowed(self):
        self.db.request = MagicMock(side_effect=DbError(409, "23503"))
        with self.assertRaises(DbError):
            self.db.insert_outbound({"client_request_id": "x"})


def sqs_record(body, receive_count=1):
    return {"messageId": "sqs-1", "receiptHandle": "handle-1", "body": body,
            "attributes": {"ApproximateReceiveCount": str(receive_count)}}


class HandlerTests(WorkerCase):
    def setUp(self):
        super().setUp()
        self.sqs = MagicMock()
        self._patch("handler._load_secrets")
        self._patch("handler._db", return_value=self.db)
        self._patch("handler._sqs", return_value=self.sqs)
        self.context = MagicMock()
        self.context.get_remaining_time_in_millis.return_value = 100000

    def handle(self, body, receive_count=1):
        return handler.lambda_handler({"Records": [sqs_record(body, receive_count)]}, self.context)

    def test_done_job_is_acknowledged(self):
        self.db.add_message()
        self.assertEqual(self.handle(json.dumps(triage_job())), {"batchItemFailures": []})
        self.assertEqual(self.message()["status"], "ready_for_question")
        kwargs = self.sqs.send_message.call_args.kwargs
        self.assertEqual(kwargs["QueueUrl"], AI_QUEUE)
        self.assertEqual(json.loads(kwargs["MessageBody"])["type"], "draft")
        self.sqs.change_message_visibility.assert_not_called()

    def test_18_invalid_job_is_acknowledged_without_writes(self):
        for body in ("not json", json.dumps({**triage_job(), "type": "embed"})):
            self.assertEqual(self.handle(body), {"batchItemFailures": []})
        self.assertEqual(self.db.writes, [])

    def test_retry_is_reported_with_backoff(self):
        self.db.add_message()
        self.triage.side_effect = llm.LLMError("openrouter", 503, "unavailable")
        self.assertEqual(self.handle(json.dumps(triage_job()), receive_count=2),
                         {"batchItemFailures": [{"itemIdentifier": "sqs-1"}]})
        self.sqs.change_message_visibility.assert_called_once_with(
            QueueUrl=AI_QUEUE, ReceiptHandle="handle-1", VisibilityTimeout=120)

    def test_backoff_failure_never_stops_the_retry(self):
        self.db.add_message()
        self.triage.side_effect = llm.LLMError("openrouter", 503, "unavailable")
        self.sqs.change_message_visibility.side_effect = OSError("sqs down")
        self.assertEqual(self.handle(json.dumps(triage_job()))["batchItemFailures"], [{"itemIdentifier": "sqs-1"}])

    def test_secrets_failure_retries(self):
        self.db.add_message()
        handler._load_secrets.side_effect = RuntimeError("No value for SSM_OPENAI_KEY")
        self.assertEqual(self.handle(json.dumps(triage_job()))["batchItemFailures"], [{"itemIdentifier": "sqs-1"}])

    def test_time_left_comes_from_the_context(self):
        question_id = self.claimed_question()
        self.db.add_message(status="ready_for_question")
        self.handle(json.dumps(draft_job(question_id)))
        self.assertEqual(self.draft.call_args.kwargs["time_left"], 85)


class LoadSecretsTests(unittest.TestCase):
    NAMES = {"SSM_SUPABASE_URL": "/p/url", "SSM_SUPABASE_KEY": "/p/key", "SSM_OPENAI_KEY": "/p/openai",
             "SSM_OPENROUTER_KEY": "/p/openrouter"}

    def setUp(self):
        handler._load_secrets.cache_clear()
        self.addCleanup(handler._load_secrets.cache_clear)

    def load(self, ssm):
        fake_boto3 = MagicMock()
        fake_boto3.client.return_value = ssm
        with patch.dict(sys.modules, {"boto3": fake_boto3}), patch.dict(os.environ, self.NAMES):
            handler._load_secrets()
            handler._load_secrets()
            return {variable: os.environ[variable] for variable, _ in handler.SECRETS}

    def test_copies_each_parameter_once_with_decryption(self):
        ssm = MagicMock()
        values = {"/p/url": "https://host.supabase.test"}
        ssm.get_parameter.side_effect = lambda Name, WithDecryption: {
            "Parameter": {"Value": values.get(Name, f"value{Name}")}}
        self.assertEqual(self.load(ssm), {"SUPABASE_URL": "https://host.supabase.test",
                                          "SUPABASE_SERVICE_ROLE_KEY": "value/p/key",
                                          "OPENAI_API_KEY": "value/p/openai",
                                          "OPENROUTER_API_KEY": "value/p/openrouter"})
        self.assertEqual(ssm.get_parameter.call_count, 4)
        self.assertTrue(all(call.kwargs["WithDecryption"] for call in ssm.get_parameter.call_args_list))

    def supabase_url(self, value):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": value}}
        return self.load(ssm)["SUPABASE_URL"]

    def test_supabase_url_ending_in_rest_v1_keeps_only_scheme_and_host(self):
        self.assertEqual(self.supabase_url("https://host.supabase.test/rest/v1/"), "https://host.supabase.test")

    def test_supabase_url_without_a_path_is_unchanged(self):
        for value in ("https://host.supabase.test", "https://host.supabase.test/"):
            handler._load_secrets.cache_clear()
            self.assertEqual(self.supabase_url(value), "https://host.supabase.test")

    def test_knowledge_and_db_build_correct_urls_from_the_stored_value(self):
        url = self.supabase_url("https://host.supabase.test/rest/v1/")
        with patch.dict(os.environ, {"SUPABASE_URL": url, "SUPABASE_SERVICE_ROLE_KEY": "key"}):
            with patch("knowledge.urlopen", return_value=FakeResponse(b"[]")) as urlopen:
                knowledge._supabase_rpc()({})
        self.assertEqual(urlopen.call_args.args[0].full_url,
                         "https://host.supabase.test/rest/v1/rpc/match_knowledge")
        with patch("db.urlopen", return_value=FakeResponse(b"[]")) as urlopen:
            Db(url, "key").request("GET", "questions")
        self.assertEqual(urlopen.call_args.args[0].full_url, "https://host.supabase.test/rest/v1/questions")

    def test_missing_value_is_a_runtime_error(self):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {}}
        with self.assertRaises(RuntimeError):
            self.load(ssm)


if __name__ == "__main__":
    unittest.main()
