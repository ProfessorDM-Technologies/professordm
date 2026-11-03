"""Tests for POST /api/send answering a question (docs/plans/creator-inbox-spec.md section 4).

No test calls Supabase or Meta. Store keeps in-memory rows behind the repository methods sender.py calls.
"""

from datetime import datetime, timedelta
import json
import logging
import sys
import unittest
from pathlib import Path
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clients import RestError, SupabaseRepository
from sender import DuplicateRequest, edit_distance, handle_send, normalize_answer, parse_tags


MESSAGE_ID = "11111111-1111-4111-8111-111111111111"
FOLLOWER_ID = "22222222-2222-4222-8222-222222222222"
CREATOR_ID = "33333333-3333-4333-8333-333333333333"
ACCOUNT_ID = "44444444-4444-4444-8444-444444444444"
REQUEST_ID = "55555555-5555-4555-8555-555555555555"
RETRY_ID = "66666666-6666-4666-8666-666666666666"
QUESTION_ID = "77777777-7777-4777-8777-777777777777"
DRAFT_ID = "88888888-8888-4888-8888-888888888888"
MESSAGE_FLAG = "99999999-9999-4999-8999-999999999991"
DRAFT_FLAG = "99999999-9999-4999-8999-999999999992"
USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

# Every private text holds PRIVATE, so the log checks can search for it.
AI_TEXT = "PRIVATE-AI Move it closer to the window."
ANSWER = "PRIVATE-ANSWER Move it closer to the window, and mist it daily."
TAG = "PRIVATE-TAG"


class Store:
    """In-memory rows behind every repository method the send API uses."""

    def __init__(self):
        self.questions = {QUESTION_ID: {"id": QUESTION_ID, "creator_id": CREATOR_ID, "status": "awaiting_creator",
                                        "origin_message_id": MESSAGE_ID, "follower_id": FOLLOWER_ID,
                                        "source": "instagram"}}
        self.drafts = {DRAFT_ID: {"id": DRAFT_ID, "question_id": QUESTION_ID, "ai_text": AI_TEXT, "status": "ready",
                                  "followup_id": None}}
        self.flags = {}
        self.tags = []
        self.question_tags = set()
        self.audit = []
        self.outbound = {}
        self.question_history = []
        self.fail = {}

    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    def add_flag(self, flag_id, target_type, target_id, status="open"):
        self.flags[flag_id] = {"id": flag_id, "target_type": target_type, "target_id": target_id, "status": status,
                               "reviewed_by": None}

    # Today's methods.
    def get_creator_by_profile(self, profile_id):
        return {"id": CREATOR_ID} if profile_id == USER_ID else None

    def get_inbound(self, message_id):
        return {"id": message_id, "follower_id": FOLLOWER_ID}

    def get_follower(self, follower_id):
        return {"id": follower_id, "ig_scoped_id": "1001", "creator_id": CREATOR_ID}

    def get_ig_account(self, creator_id):
        return {"id": ACCOUNT_ID, "creator_id": creator_id, "ig_user_id": "2002"}

    def create_outbound(self, row):
        self._maybe_fail("create_outbound")
        if any(item["client_request_id"] == row["client_request_id"] for item in self.outbound.values()):
            raise DuplicateRequest()
        value = {"id": f"outbound-{len(self.outbound) + 1}", **row}
        self.outbound[value["id"]] = value
        return dict(value)

    def get_outbound_by_client_request_id(self, request_id):
        return next((dict(row) for row in self.outbound.values() if row["client_request_id"] == request_id), None)

    def update_outbound(self, outbound_id, *, status, meta_message_id=None, attempts=None):
        self._maybe_fail(f"update_outbound_{status}")
        row = self.outbound[outbound_id]
        row["status"] = status
        if meta_message_id is not None:
            row["meta_message_id"] = meta_message_id
        if attempts is not None:
            row["attempts"] = attempts
        return dict(row)

    # Answer methods.
    def get_question(self, question_id):
        row = self.questions.get(question_id)
        return dict(row) if row else None

    def get_question_draft(self, question_id):
        row = next((row for row in self.drafts.values()
                    if row["question_id"] == question_id and row["followup_id"] is None), None)
        return {key: row[key] for key in ("id", "ai_text", "status")} if row else None

    def get_open_flag_ids(self, message_id, draft_id):
        return [flag["id"] for flag in self.flags.values() if flag["status"] == "open" and (
            (flag["target_type"] == "message" and flag["target_id"] == message_id)
            or (draft_id and flag["target_type"] == "draft" and flag["target_id"] == draft_id))]

    def update_question(self, question_id, expected_status, values):
        self._maybe_fail(f"question_{values['status']}")
        row = self.questions.get(question_id)
        if not row or row["status"] != expected_status:
            return None
        row.update(values)
        self.question_history.append(values["status"])
        return dict(row)

    def update_draft(self, draft_id, values):
        self.drafts[draft_id].update(values)
        return dict(self.drafts[draft_id])

    def insert_draft(self, row):
        value = {"id": f"draft-{len(self.drafts) + 1}", "followup_id": None, **row}
        self.drafts[value["id"]] = value
        return dict(value)

    def mark_flags_reviewed(self, flag_ids, user_id):
        rows = []
        for flag_id in flag_ids:
            flag = self.flags[flag_id]
            if flag["status"] == "open":
                flag.update(status="creator_reviewed", reviewed_by=user_id)
                rows.append(dict(flag))
        return rows

    def find_or_create_tag(self, creator_id, name):
        tag = next((tag for tag in self.tags if tag["creator_id"] == creator_id and tag["name"] == name), None)
        if not tag:
            tag = {"id": f"tag-{len(self.tags) + 1}", "creator_id": creator_id, "name": name}
            self.tags.append(tag)
        return dict(tag)

    def add_question_tags(self, question_id, tag_ids):
        self.question_tags |= {(question_id, tag_id) for tag_id in tag_ids}

    def insert_audit(self, row):
        self._maybe_fail("insert_audit")
        self.audit.append(row)


class Auth:
    def user_id(self, jwt):
        return USER_ID if jwt == "user-jwt" else None


class Tokens:
    token = "private-test-token"

    def for_account(self, ig_user_id):
        return self.token


class Graph:
    def __init__(self):
        self.sends = []
        self.send_error = None
        self.validate_error = None

    def validate_send_account(self, token, ig_user_id):
        if self.validate_error:
            raise self.validate_error

    def send(self, token, ig_user_id, recipient, text):
        self.sends.append(text)
        if self.send_error:
            raise self.send_error
        return f"meta-message-{len(self.sends)}"


def body(**fields):
    data = {"inbound_message_id": MESSAGE_ID, "text": ANSWER, "client_request_id": REQUEST_ID,
            "question_id": QUESTION_ID, "tags": [TAG], "reviewed_flag_ids": []}
    data.update(fields)
    return {key: value for key, value in data.items() if value is not ...}


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.store, self.graph, self.tokens = Store(), Graph(), Tokens()
        self.logs = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda record: self.logs.append(record.getMessage())
        logging.getLogger("sender").addHandler(handler)
        self.addCleanup(logging.getLogger("sender").removeHandler, handler)

    def tearDown(self):
        self.assertFalse([line for line in self.logs if "PRIVATE" in line or "private" in line])

    def send(self, **fields):
        event = {"httpMethod": "POST", "headers": {"Authorization": "Bearer user-jwt"}, "body": json.dumps(body(**fields))}
        result = handle_send(event, auth=Auth(), repository=self.store, profile_tokens=self.tokens, graph=self.graph)
        self.assertNotIn("PRIVATE", result["body"])
        return result["statusCode"], json.loads(result["body"])

    def question(self):
        return self.store.questions[QUESTION_ID]

    def assert_untouched(self):
        self.assertEqual(self.question()["status"], "awaiting_creator")
        self.assertEqual(self.store.question_history, [])
        self.assertEqual(self.store.outbound, {})
        self.assertEqual(self.graph.sends, [])
        self.assertEqual(self.store.audit, [])

    def test_manual_reply_is_unchanged_without_question_id(self):
        status, data = self.send(question_id=..., tags=..., reviewed_flag_ids=..., text="A manual reply")
        self.assertEqual((status, data["status"], data["meta_message_id"]), (200, "sent", "meta-message-1"))
        row = next(iter(self.store.outbound.values()))
        self.assertEqual((row["type"], row["draft_id"], row["attempts"]), ("answer", None, 1))
        self.assertEqual(self.question()["status"], "awaiting_creator")
        self.assertEqual((self.store.audit, self.store.tags), ([], []))

    def test_manual_reply_ignores_answer_fields_without_question_id(self):
        status, _ = self.send(question_id=None, tags="not a list", reviewed_flag_ids="bad", text="A manual reply")
        self.assertEqual(status, 200)
        self.assertEqual(self.question()["status"], "awaiting_creator")

    def test_answer_with_edit_and_tag_is_delivered(self):
        self.store.add_flag(MESSAGE_FLAG, "message", MESSAGE_ID)
        self.store.add_flag(DRAFT_FLAG, "draft", DRAFT_ID)
        before = datetime.now().astimezone()
        status, data = self.send(tags=[" Calathea ", TAG], reviewed_flag_ids=[MESSAGE_FLAG, DRAFT_FLAG.upper()])
        self.assertEqual(status, 200)
        self.assertEqual(set(data), {"id", "status", "meta_message_id"})
        self.assertEqual((data["status"], data["meta_message_id"]), ("sent", "meta-message-1"))
        self.assertEqual(self.graph.sends, [ANSWER])

        question = self.question()
        self.assertEqual(question["status"], "delivered")
        self.assertEqual(self.store.question_history, ["approved", "delivering", "delivered"])
        delivered_at = datetime.fromisoformat(question["delivered_at"])
        self.assertGreaterEqual(delivered_at, before)
        self.assertEqual(datetime.fromisoformat(question["hold_ends_at"]) - delivered_at, timedelta(days=3))

        draft = self.store.drafts[DRAFT_ID]
        self.assertEqual((draft["status"], draft["final_text"], draft["ai_text"]), ("approved", ANSWER, AI_TEXT))
        self.assertEqual(draft["edit_distance"], edit_distance(AI_TEXT, ANSWER))
        self.assertGreater(draft["edit_distance"], 0)
        self.assertIsNotNone(draft["approved_at"])

        outbound = self.store.outbound[data["id"]]
        self.assertEqual((outbound["type"], outbound["draft_id"], outbound["status"], outbound["text"]),
                         ("answer", DRAFT_ID, "sent", ANSWER))
        for flag in self.store.flags.values():
            self.assertEqual((flag["status"], flag["reviewed_by"]), ("creator_reviewed", USER_ID))
        self.assertEqual(sorted(tag["name"] for tag in self.store.tags), ["calathea", TAG.lower()])
        self.assertEqual(len(self.store.question_tags), 2)

        self.assertEqual(len(self.store.audit), 1)
        audit = self.store.audit[0]
        self.assertEqual((audit["actor_id"], audit["action"], audit["entity"], audit["entity_id"]),
                         (USER_ID, "answer.approved", "question", QUESTION_ID))
        self.assertEqual(audit["before_after"], {"edit_distance": draft["edit_distance"], "tag_count": 2,
                                                 "had_ai_draft": True, "flags_reviewed": 2})
        self.assertNotIn("PRIVATE", json.dumps(audit))
        self.assertNotIn("calathea", json.dumps(audit))

    def test_unchanged_text_needs_an_edit(self):
        for text in (AI_TEXT, f"  {AI_TEXT}  ", AI_TEXT.replace(" ", "\n\t "), AI_TEXT.replace(" ", " ")):
            with self.subTest(text=repr(text[:20])):
                self.assertEqual(self.send(text=text), (422, {"error": "edit_required"}))
        self.assert_untouched()

    def test_tags_missing_or_invalid(self):
        cases = [..., None, [], [" "], ["a" * 41], [str(n) for n in range(6)], "calathea", [1]]
        for tags in cases:
            with self.subTest(tags=tags):
                self.assertEqual(self.send(tags=tags), (422, {"error": "tags_required"}))
        self.assert_untouched()

    def test_unreviewed_flag_blocks_the_send(self):
        self.store.add_flag(MESSAGE_FLAG, "message", MESSAGE_ID)
        self.store.add_flag(DRAFT_FLAG, "draft", DRAFT_ID)
        for reviewed in ([], [MESSAGE_FLAG], [DRAFT_FLAG]):
            with self.subTest(reviewed=reviewed):
                self.assertEqual(self.send(reviewed_flag_ids=reviewed), (422, {"error": "flags_unreviewed"}))
        self.assert_untouched()
        self.assertTrue(all(flag["status"] == "open" for flag in self.store.flags.values()))

    def test_only_this_questions_open_flags_count_and_get_reviewed(self):
        self.store.add_flag(MESSAGE_FLAG, "message", MESSAGE_ID, status="creator_reviewed")
        self.store.add_flag(DRAFT_FLAG, "message", "another-message")
        status, _ = self.send(reviewed_flag_ids=[DRAFT_FLAG])
        self.assertEqual(status, 200)
        self.assertEqual(self.store.flags[DRAFT_FLAG]["status"], "open")
        self.assertEqual(self.store.audit[0]["before_after"]["flags_reviewed"], 0)

    def test_no_drafts_row_inserts_one_without_an_edit_check(self):
        self.store.drafts.clear()
        status, data = self.send(text=AI_TEXT)
        self.assertEqual((status, data["status"]), (200, "sent"))
        draft = next(iter(self.store.drafts.values()))
        self.assertEqual((draft["question_id"], draft["ai_text"], draft["citations"], draft["final_text"],
                          draft["status"]), (QUESTION_ID, None, [], AI_TEXT, "approved"))
        self.assertIsNotNone(draft["approved_at"])
        self.assertEqual(self.store.outbound[data["id"]]["draft_id"], draft["id"])
        self.assertEqual(self.store.audit[0]["before_after"]["edit_distance"], None)
        self.assertFalse(self.store.audit[0]["before_after"]["had_ai_draft"])
        self.assertEqual(self.question()["status"], "delivered")

    def test_draft_without_ai_text_has_no_edit_check_and_no_distance(self):
        self.store.drafts[DRAFT_ID]["ai_text"] = None
        status, _ = self.send()
        self.assertEqual(status, 200)
        self.assertIsNone(self.store.drafts[DRAFT_ID]["edit_distance"])

    def test_question_not_awaiting_creator(self):
        for state in ("delivered", "approved", "delivering", "paid", "drafting"):
            with self.subTest(state=state):
                self.question()["status"] = state
                self.assertEqual(self.send(), (409, {"error": "not_awaiting_answer"}))
        self.assertEqual((self.store.outbound, self.graph.sends), ({}, []))

    def test_claim_lost_to_another_request(self):
        original = self.store.update_question

        def someone_else_claims(question_id, expected, values):
            if values["status"] == "approved":
                return None
            return original(question_id, expected, values)

        self.store.update_question = someone_else_claims
        self.assertEqual(self.send(), (409, {"error": "not_awaiting_answer"}))
        self.assertEqual((self.store.outbound, self.graph.sends, self.store.audit), ({}, [], []))

    def test_double_request_calls_meta_once(self):
        first = self.send()
        second = self.send()
        self.assertEqual(first, second)
        self.assertEqual(first[0], 200)
        self.assertEqual(len(self.graph.sends), 1)
        self.assertEqual((len(self.store.outbound), len(self.store.audit)), (1, 1))

    def test_same_request_id_with_different_text_is_a_conflict(self):
        self.send()
        self.assertEqual(self.send(text="PRIVATE-OTHER answer")[0], 409)
        self.assertEqual(len(self.graph.sends), 1)

    def test_meta_refusal_returns_502_and_reopens_the_question(self):
        self.graph.send_error = RestError(400, 10, "OAuthException")
        self.assertEqual(self.send(), (502, {"error": "delivery_failed"}))
        self.assertEqual(self.question()["status"], "awaiting_creator")
        self.assertEqual(self.store.question_history, ["approved", "delivering", "awaiting_creator"])
        outbound = next(iter(self.store.outbound.values()))
        self.assertEqual((outbound["status"], outbound["attempts"]), ("failed", 1))
        self.assertEqual(self.store.drafts[DRAFT_ID]["final_text"], ANSWER)
        self.assertEqual(len(self.graph.sends), 1)

    def test_retry_after_502_with_a_new_id_sends_once_and_delivers(self):
        self.graph.send_error = RestError(400, 10, "OAuthException")
        self.assertEqual(self.send()[0], 502)
        self.graph.send_error = None
        status, data = self.send(client_request_id=RETRY_ID)
        self.assertEqual((status, data["status"]), (200, "sent"))
        self.assertEqual(len(self.graph.sends), 2)
        self.assertEqual(self.question()["status"], "delivered")
        self.assertEqual(sorted(row["status"] for row in self.store.outbound.values()), ["failed", "sent"])
        self.assertEqual(len(self.store.drafts), 1)
        self.assertEqual(self.store.drafts[DRAFT_ID]["status"], "approved")

    def test_retry_with_the_failed_id_returns_the_failed_row(self):
        self.graph.send_error = RestError(400, 10, "OAuthException")
        self.send()
        status, data = self.send()
        self.assertEqual((status, data["status"]), (200, "failed"))
        self.assertEqual(len(self.graph.sends), 1)

    def test_unknown_meta_outcome_is_500_and_never_sends_twice(self):
        for error in (URLError("timed out"), TimeoutError(), RestError(500, 2, "OAuthException"),
                      ValueError("Meta did not confirm the message and recipient")):
            with self.subTest(error=type(error).__name__):
                self.setUp()
                self.graph.send_error = error
                status, data = self.send()
                self.assertEqual((status, data["status"], data["error"]), (500, "pending", "delivery_unconfirmed"))
                self.assertEqual(self.question()["status"], "delivering")
                outbound = self.store.outbound[data["id"]]
                self.assertEqual((outbound["status"], outbound["attempts"]), ("pending", 1))
                self.assertEqual(self.send(), (200, {"id": data["id"], "status": "pending", "meta_message_id": None}))
                self.assertEqual(len(self.graph.sends), 1)

    def test_token_rejected_by_meta_is_502_and_nothing_sent(self):
        self.graph.validate_error = RestError(400, 190, "OAuthException")
        self.assertEqual(self.send(), (502, {"error": "delivery_failed"}))
        self.assertEqual(self.graph.sends, [])
        self.assertEqual(self.question()["status"], "awaiting_creator")
        self.assertEqual(next(iter(self.store.outbound.values()))["status"], "failed")

    def test_failure_before_meta_is_500_marks_failed_and_reopens(self):
        for setup in ("no_token", "token_mismatch", "attempt_record"):
            with self.subTest(setup=setup):
                self.setUp()
                if setup == "no_token":
                    self.tokens.token = None
                elif setup == "token_mismatch":
                    self.graph.validate_error = ValueError("Instagram send token does not match receiving account")
                else:
                    self.store.fail["update_outbound_pending"] = RestError(503, "unavailable")
                status, data = self.send()
                self.assertEqual((status, data["status"]), (500, "failed"))
                self.assertEqual(self.graph.sends, [])
                self.assertEqual(self.question()["status"], "awaiting_creator")
                self.assertEqual(self.send()[1]["status"], "failed")
                self.assertEqual(self.graph.sends, [])

    def test_save_failure_reopens_the_question_and_the_same_id_can_retry(self):
        self.store.fail["insert_audit"] = RestError(503, "unavailable")
        self.assertEqual(self.send(), (500, {"error": "Send processing failed"}))
        self.assertEqual(self.question()["status"], "awaiting_creator")
        self.assertEqual((self.store.outbound, self.graph.sends), ({}, []))
        del self.store.fail["insert_audit"]
        status, data = self.send()
        self.assertEqual((status, data["status"]), (200, "sent"))
        self.assertEqual(len(self.graph.sends), 1)

    def test_delivered_status_failure_still_reports_the_sent_dm(self):
        self.store.fail["question_delivered"] = RestError(503, "unavailable")
        status, data = self.send()
        self.assertEqual((status, data["status"]), (200, "sent"))
        self.assertEqual(self.question()["status"], "delivering")
        self.assertEqual(len(self.graph.sends), 1)

    def test_other_creators_or_missing_question_is_404(self):
        self.question()["creator_id"] = "another-creator"
        self.assertEqual(self.send(), (404, {"error": "Question unavailable"}))
        self.assertEqual(self.send(question_id=RETRY_ID), (404, {"error": "Question unavailable"}))
        self.assertEqual(self.question()["status"], "awaiting_creator")
        self.assertEqual(self.graph.sends, [])

    def test_wrong_origin_message_or_source_is_400(self):
        self.question()["origin_message_id"] = RETRY_ID
        self.assertEqual(self.send()[0], 400)
        self.question().update(origin_message_id=MESSAGE_ID, source="knowledge_app")
        self.assertEqual(self.send()[0], 400)
        self.assertEqual(self.graph.sends, [])

    def test_malformed_answer_fields_are_400(self):
        for fields in ({"question_id": "bad"}, {"question_id": 5}, {"reviewed_flag_ids": "x"},
                       {"reviewed_flag_ids": ["bad"]}, {"text": " "}, {"text": "a" * 1000}):
            with self.subTest(fields=fields):
                self.assertEqual(self.send(**fields)[0], 400)
        self.assert_untouched()

    def test_logs_hold_no_answer_or_tag_text(self):
        self.store.add_flag(MESSAGE_FLAG, "message", MESSAGE_ID)
        self.send(reviewed_flag_ids=[MESSAGE_FLAG])
        self.graph.send_error = RestError(400, 10, "OAuthException")
        self.question()["status"] = "awaiting_creator"
        self.send(client_request_id=RETRY_ID)
        self.assertTrue(self.logs)
        joined = "\n".join(self.logs)
        self.assertNotIn(TAG.lower(), joined)


class HelperTests(unittest.TestCase):
    def test_normalize_answer_matches_javascript_whitespace(self):
        self.assertEqual(normalize_answer(" a\t\n b  c﻿ "), "a b c")
        self.assertEqual(normalize_answer("a\x1cb"), "a\x1cb")

    def test_parse_tags(self):
        self.assertEqual(parse_tags([" Calathea ", "calathea", "LIGHT"]), ["calathea", "light"])
        self.assertEqual(parse_tags(["a" * 40]), ["a" * 40])
        self.assertEqual(parse_tags(["😀" * 20]), ["😀" * 20])
        for raw in (None, [], [""], ["a" * 41], ["😀" * 21], [str(n) for n in range(6)], "a", [None]):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_tags(raw))

    def test_edit_distance(self):
        for before, after, distance in (("", "", 0), ("", "abc", 3), ("kitten", "sitting", 3), ("flaw", "lawn", 2),
                                        ("same", "same", 0), ("😀a", "a", 1)):
            with self.subTest(before=before, after=after):
                self.assertEqual(edit_distance(before, after), distance)
                self.assertEqual(edit_distance(after, before), distance)


class RecordingRest:
    def __init__(self, response=None):
        self.calls = []
        self.response = [] if response is None else response

    def request(self, method, path, *, params=None, body=None, prefer=None, timeout=None):
        self.calls.append((method, path, params, body, prefer))
        return self.response


class RepositoryQueryTests(unittest.TestCase):
    def test_answer_queries(self):
        rest = RecordingRest([{"id": "x"}])
        repository = SupabaseRepository(rest)
        repository.get_question(QUESTION_ID)
        repository.get_question_draft(QUESTION_ID)
        repository.get_open_flag_ids(MESSAGE_ID, DRAFT_ID)
        repository.get_open_flag_ids(MESSAGE_ID, None)
        repository.update_question(QUESTION_ID, "awaiting_creator", {"status": "approved"})
        repository.mark_flags_reviewed([MESSAGE_FLAG, DRAFT_FLAG], USER_ID)
        repository.add_question_tags(QUESTION_ID, ["t1"])
        self.assertEqual(rest.calls, [
            ("GET", "questions", {"id": f"eq.{QUESTION_ID}",
                                  "select": "id,creator_id,status,origin_message_id,follower_id,source", "limit": "1"},
             None, None),
            ("GET", "drafts", {"question_id": f"eq.{QUESTION_ID}", "followup_id": "is.null",
                               "select": "id,ai_text,status", "limit": "1"}, None, None),
            ("GET", "safety_flags", {"status": "eq.open", "or": f"(and(target_type.eq.message,target_id.eq.{MESSAGE_ID}),"
                                     f"and(target_type.eq.draft,target_id.eq.{DRAFT_ID}))", "select": "id"}, None, None),
            ("GET", "safety_flags", {"status": "eq.open",
                                     "or": f"(and(target_type.eq.message,target_id.eq.{MESSAGE_ID}))", "select": "id"},
             None, None),
            ("PATCH", "questions", {"id": f"eq.{QUESTION_ID}", "status": "eq.awaiting_creator"}, {"status": "approved"},
             "return=representation"),
            ("PATCH", "safety_flags", {"id": f"in.({MESSAGE_FLAG},{DRAFT_FLAG})", "status": "eq.open"},
             {"status": "creator_reviewed", "reviewed_by": USER_ID}, "return=representation"),
            ("POST", "question_tags", {"on_conflict": "question_id,tag_id"},
             [{"question_id": QUESTION_ID, "tag_id": "t1"}], "resolution=ignore-duplicates"),
        ])

    def test_no_flags_means_no_request(self):
        rest = RecordingRest()
        self.assertEqual(SupabaseRepository(rest).mark_flags_reviewed([], USER_ID), [])
        self.assertEqual(rest.calls, [])

    def test_tag_is_reused_or_created(self):
        rest = RecordingRest([{"id": "tag-1"}])
        self.assertEqual(SupabaseRepository(rest).find_or_create_tag(CREATOR_ID, "calathea"), {"id": "tag-1"})
        self.assertEqual([call[0] for call in rest.calls], ["GET"])
        rest = RecordingRest([])
        SupabaseRepository(rest).find_or_create_tag(CREATOR_ID, "calathea")
        self.assertEqual(rest.calls[-1][:4], ("POST", "tags", None, {"creator_id": CREATOR_ID, "name": "calathea"}))


if __name__ == "__main__":
    unittest.main()
