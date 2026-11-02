import json
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clients import RestError
from outbound import handle_outbound


OUTBOUND_ID = "11111111-1111-4111-8111-111111111111"
FOLLOWER_ID = "22222222-2222-4222-8222-222222222222"
CREATOR_ID = "33333333-3333-4333-8333-333333333333"
TEXT = "PRIVATE-TEXT which plant is it?"


def job(job_type="clarification"):
    return {"v": 1, "type": job_type, "id": f"outbound:{OUTBOUND_ID}", "creatorId": CREATOR_ID, "traceId": "trace-1",
            "createdAt": "2026-11-01T12:00:00+00:00", "payload": {"outboundMessageId": OUTBOUND_ID}}


class FakeRest:
    def __init__(self, row):
        self.row = row
        self.down = False

    def request(self, method, path, *, params=None, body=None, prefer=None):
        if self.down:
            raise RestError(503, "unavailable")
        if path != "outbound_messages" or self.row is None:
            return []
        if method == "GET":
            return [dict(self.row)]
        if self.row["status"] != "pending" or self.row["attempts"] != 0:
            return []
        self.row.update(body)
        return [dict(self.row)]


class FakeRepository:
    def __init__(self, rest):
        self.rest = rest
        self.follower = {"id": FOLLOWER_ID, "ig_scoped_id": "1001", "creator_id": CREATOR_ID}
        self.account = {"id": "account", "creator_id": CREATOR_ID, "ig_user_id": "2002"}
        self.fail_updates = False

    def get_follower(self, follower_id):
        return self.follower

    def get_ig_account(self, creator_id):
        return self.account

    def update_outbound(self, outbound_id, *, status, meta_message_id=None, attempts=None):
        if self.fail_updates:
            raise RestError(503, "unavailable")
        self.rest.row.update({"status": status})
        if meta_message_id is not None:
            self.rest.row["meta_message_id"] = meta_message_id
        if attempts is not None:
            self.rest.row["attempts"] = attempts
        return self.rest.row


class FakeTokens:
    token = "token"

    def for_account(self, ig_user_id):
        return self.token


class FakeGraph:
    def __init__(self):
        self.sends = []
        self.error = None

    def validate_send_account(self, token, ig_user_id):
        pass

    def send(self, token, ig_user_id, recipient, text):
        self.sends.append((token, ig_user_id, recipient, text))
        if self.error:
            raise self.error
        return "meta-message-1"


class OutboundTests(unittest.TestCase):
    def setUp(self):
        self.rest = FakeRest({"id": OUTBOUND_ID, "type": "clarification", "text": TEXT, "status": "pending",
                              "attempts": 0, "follower_id": FOLLOWER_ID, "creator_id": CREATOR_ID})
        self.repository = FakeRepository(self.rest)
        self.tokens = FakeTokens()
        self.graph = FakeGraph()
        self.logs = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda record: self.logs.append(record.getMessage())
        for name in ("outbound", "sender"):
            logging.getLogger(name).addHandler(handler)
            self.addCleanup(logging.getLogger(name).removeHandler, handler)

    def tearDown(self):
        self.assertFalse([line for line in self.logs if "PRIVATE-" in line])

    def handle(self, message=None):
        return handle_outbound(message or job(), rest=self.rest, repository=self.repository,
                               profile_tokens=self.tokens, graph=self.graph)

    def test_01_pending_clarification_is_sent(self):
        self.assertEqual(self.handle(), "done")
        self.assertEqual(self.graph.sends, [("token", "2002", "1001", TEXT)])
        self.assertEqual((self.rest.row["status"], self.rest.row["meta_message_id"], self.rest.row["attempts"]),
                         ("sent", "meta-message-1", 1))

    def test_decline_is_sent(self):
        self.rest.row["type"] = "decline"
        self.assertEqual(self.handle(job("decline")), "done")
        self.assertEqual(len(self.graph.sends), 1)

    def test_02_same_job_twice_sends_once(self):
        self.handle()
        self.assertEqual(self.handle(), "done")
        self.assertEqual(len(self.graph.sends), 1)

    def test_02_claimed_but_unfinished_row_is_not_sent_again(self):
        self.rest.row["attempts"] = 1
        self.assertEqual(self.handle(), "done")
        self.assertEqual(self.graph.sends, [])

    def test_lost_claim_sends_nothing(self):
        real_load = self.rest.request

        def other_run_claims_first(method, path, **kwargs):
            if method == "PATCH":
                self.rest.row["attempts"] = 1
            return real_load(method, path, **kwargs)

        self.rest.request = other_run_claims_first
        self.assertEqual(self.handle(), "done")
        self.assertEqual(self.graph.sends, [])

    def test_03_meta_failure_marks_failed_without_retry(self):
        self.graph.error = RestError(500, 2, "OAuthException")
        self.assertEqual(self.handle(), "done")
        self.assertEqual((self.rest.row["status"], self.rest.row["attempts"]), ("failed", 1))
        self.assertEqual(self.handle(), "done")
        self.assertEqual(len(self.graph.sends), 1)

    def test_missing_token_marks_failed(self):
        self.tokens.token = None
        self.assertEqual(self.handle(), "done")
        self.assertEqual((self.rest.row["status"], self.rest.row["attempts"]), ("failed", 1))
        self.assertEqual(self.graph.sends, [])

    def test_failed_status_write_after_send_never_resends(self):
        self.repository.fail_updates = True
        self.assertEqual(self.handle(), "done")
        self.assertEqual(self.handle(), "done")
        self.assertEqual(len(self.graph.sends), 1)

    def test_04_answer_type_is_acknowledged_and_never_sent(self):
        self.rest.row["type"] = "answer"
        self.assertEqual(self.handle(job("answer")), "done")
        self.assertEqual(self.graph.sends, [])
        self.assertEqual((self.rest.row["status"], self.rest.row["attempts"]), ("pending", 0))

    def test_invalid_jobs_are_acknowledged(self):
        for message in ({**job(), "v": 2}, {**job(), "payload": {}}, {**job(), "payload": None}, [1]):
            self.assertEqual(self.handle(message), "done")
        self.assertEqual(self.graph.sends, [])

    def test_missing_row_is_acknowledged(self):
        self.rest.row = None
        self.assertEqual(self.handle(), "done")

    def test_05_text_over_1000_bytes_is_failed(self):
        self.rest.row["text"] = "é" * 501
        self.assertEqual(self.handle(), "done")
        self.assertEqual((self.rest.row["status"], self.rest.row["attempts"]), ("failed", 0))
        self.assertEqual(self.graph.sends, [])

    def test_text_of_1000_bytes_is_sent(self):
        self.rest.row["text"] = "é" * 500
        self.assertEqual(self.handle(), "done")
        self.assertEqual(self.rest.row["status"], "sent")

    def test_blank_text_is_failed(self):
        self.rest.row["text"] = "   "
        self.assertEqual(self.handle(), "done")
        self.assertEqual(self.rest.row["status"], "failed")

    def test_missing_follower_or_account_is_failed(self):
        for attribute in ("follower", "account"):
            self.rest.row.update({"status": "pending", "attempts": 0})
            saved = getattr(self.repository, attribute)
            setattr(self.repository, attribute, None)
            self.assertEqual(self.handle(), "done")
            self.assertEqual(self.rest.row["status"], "failed")
            setattr(self.repository, attribute, saved)
        self.assertEqual(self.graph.sends, [])

    def test_follower_of_another_creator_is_failed(self):
        self.repository.follower["creator_id"] = "another-creator"
        self.assertEqual(self.handle(), "done")
        self.assertEqual(self.rest.row["status"], "failed")
        self.assertEqual(self.graph.sends, [])

    def test_06_supabase_down_before_the_claim_retries(self):
        self.rest.down = True
        self.assertEqual(self.handle(), "retry")
        self.assertEqual(self.graph.sends, [])


class OutboundHandlerTests(unittest.TestCase):
    def setUp(self):
        self.runtime = MagicMock()
        modules = patch.dict(sys.modules, {"runtime": self.runtime})
        modules.start()
        self.addCleanup(modules.stop)
        env = patch.dict(os.environ, {"SSM_INSTAGRAM_PROFILE_TOKEN_PREFIX": "/tokens",
                                      "META_GRAPH_API_VERSION": "v26.0"})
        env.start()
        self.addCleanup(env.stop)
        import outbound_handler
        self.addCleanup(sys.modules.pop, "outbound_handler", None)
        self.module = outbound_handler
        self.logger = logging.getLogger("outbound_handler")
        self.logger.disabled = True
        self.addCleanup(setattr, self.logger, "disabled", False)

    def event(self, body):
        return {"Records": [{"messageId": "sqs-1", "body": body}]}

    def test_retry_is_reported(self):
        with patch.object(self.module, "handle_outbound", return_value="retry") as handle:
            result = self.module.lambda_handler(self.event(json.dumps(job())), None)
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "sqs-1"}]})
        self.assertEqual(handle.call_args.args[0], job())
        self.assertEqual(handle.call_args.kwargs["profile_tokens"].prefix, "/tokens")

    def test_done_is_acknowledged(self):
        with patch.object(self.module, "handle_outbound", return_value="done"):
            self.assertEqual(self.module.lambda_handler(self.event(json.dumps(job())), None),
                             {"batchItemFailures": []})

    def test_malformed_body_is_acknowledged(self):
        self.assertEqual(self.module.lambda_handler(self.event("not json"), None), {"batchItemFailures": []})

    def test_setup_failure_retries(self):
        self.runtime._supabase.side_effect = RuntimeError("Missing SSM_SUPABASE_URL parameter name")
        self.assertEqual(self.module.lambda_handler(self.event(json.dumps(job())), None),
                         {"batchItemFailures": [{"itemIdentifier": "sqs-1"}]})


if __name__ == "__main__":
    unittest.main()
