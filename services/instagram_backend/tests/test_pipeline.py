import base64
import json
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sender import DuplicateRequest, handle_send
from clients import RestError
from webhook import handle_webhook


MESSAGE_ID = "11111111-1111-4111-8111-111111111111"
FOLLOWER_ID = "22222222-2222-4222-8222-222222222222"
CREATOR_ID = "33333333-3333-4333-8333-333333333333"
ACCOUNT_ID = "44444444-4444-4444-8444-444444444444"
REQUEST_ID = "55555555-5555-4555-8555-555555555555"


def webhook_event(body, *, encoded=False, headers=None):
    raw = json.dumps(body, separators=(",", ":")).encode()
    return {
        "httpMethod": "POST",
        "headers": headers or {},
        "body": base64.b64encode(raw).decode() if encoded else raw.decode(),
        "isBase64Encoded": encoded,
    }


def instagram_message(recipient="creator-ig-id", *, text="Hello"):
    return {
        "object": "instagram",
        "entry": [{"messaging": [{
            "sender": {"id": "follower-ig-id"},
            "recipient": {"id": recipient},
            "message": {"mid": "meta-mid-1", "text": text},
        }]}],
    }


class InboundStore:
    def __init__(self, known=True, username="known_handle", existing=True):
        self.known = known
        self.username = username
        self.existing = existing
        self.messages = {}
        self.follower_calls = 0
        self.username_updates = []

    def find_account_by_ig_user_id(self, recipient):
        return {"id": ACCOUNT_ID, "creator_id": CREATOR_ID} if self.known else None

    def upsert_follower(self, creator_id, sender_id, received_at):
        self.follower_calls += 1
        self.existing = True
        return {"id": FOLLOWER_ID, "username": self.username}

    def update_follower_username_if_missing(self, follower_id, username):
        self.username_updates.append((follower_id, username))
        if self.username is None:
            self.username = username
            return True
        return False

    def upsert_inbound(self, mid, follower_id, text):
        self.messages.setdefault(mid, {"id": MESSAGE_ID, "follower_id": follower_id, "text": text})
        return self.messages[mid]


class Publisher:
    def __init__(self):
        self.jobs = []

    def publish(self, message_id, creator_id):
        self.jobs.append((message_id, creator_id))


class ProfileTokens:
    def __init__(self, token="private-test-token"):
        self.token = token
        self.account_ids = []

    def for_account(self, account_id):
        self.account_ids.append(account_id)
        return self.token


class ProfileGraph:
    def __init__(self, profile=None, error=None):
        self.profile = profile if profile is not None else {"id": "follower-ig-id", "username": "new_handle", "name": "A name"}
        self.error = error
        self.calls = []

    def user_profile(self, token, ig_user_id, ig_scoped_id):
        self.calls.append((token, ig_user_id, ig_scoped_id))
        if self.error:
            raise self.error
        return self.profile


class WebhookTests(unittest.TestCase):
    def test_verification_get_accepts_only_matching_token(self):
        store, publisher = InboundStore(), Publisher()
        event = {"httpMethod": "GET", "queryStringParameters": {
            "hub.mode": "subscribe", "hub.verify_token": "test-token", "hub.challenge": "challenge-123",
        }}
        good = handle_webhook(event, verify_token="test-token", repository=store, publisher=publisher, profile_tokens=ProfileTokens(), graph=ProfileGraph())
        bad = handle_webhook(event, verify_token="wrong", repository=store, publisher=publisher, profile_tokens=ProfileTokens(), graph=ProfileGraph())
        self.assertEqual((good["statusCode"], good["body"]), (200, "challenge-123"))
        self.assertEqual(bad["statusCode"], 403)

    def test_post_without_signature_parses_persists_and_publishes(self):
        store, publisher = InboundStore(), Publisher()
        with self.assertLogs("webhook", level="INFO") as logs:
            result = handle_webhook(webhook_event(instagram_message()),
                                    verify_token="test-token", repository=store, publisher=publisher, profile_tokens=ProfileTokens(), graph=ProfileGraph())
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(store.follower_calls, 1)
        self.assertEqual(len(store.messages), 1)
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])
        self.assertIn("stage=json_parse PASS", "\n".join(logs.output))
        self.assertIn("stage=sqs_publish PASS", "\n".join(logs.output))

    def test_get_verification_stays_strict(self):
        result = handle_webhook({"httpMethod": "GET", "queryStringParameters": {
            "hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "x",
        }}, verify_token="test-token", repository=None, publisher=None, profile_tokens=None, graph=None)
        self.assertEqual(result["statusCode"], 403)

    def test_post_ignores_signature_headers(self):
        store, publisher = InboundStore(), Publisher()
        event = webhook_event(instagram_message(), headers={"X-Hub-Signature-256": "invalid"})
        result = handle_webhook(event, verify_token="test-token", repository=store, publisher=publisher, profile_tokens=ProfileTokens(), graph=ProfileGraph())
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])

    def test_duplicate_mid_creates_one_row_and_uses_stable_job_identity(self):
        store, publisher = InboundStore(username=None), Publisher()
        tokens, graph = ProfileTokens(), ProfileGraph()
        event = webhook_event(instagram_message(), encoded=True)
        for _ in range(2):
            result = handle_webhook(event, verify_token="test-token", repository=store, publisher=publisher, profile_tokens=tokens, graph=graph)
            self.assertEqual(result["statusCode"], 200)
        self.assertEqual(len(store.messages), 1)
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID), (MESSAGE_ID, CREATOR_ID)])
        self.assertEqual(len(graph.calls), 1)
        self.assertEqual(store.username_updates, [(FOLLOWER_ID, "new_handle")])

    def test_unknown_recipient_and_unsupported_event_do_not_write(self):
        store, publisher = InboundStore(known=False), Publisher()
        first = handle_webhook(webhook_event(instagram_message()), verify_token="test-token", repository=store, publisher=publisher, profile_tokens=ProfileTokens(), graph=ProfileGraph())
        second = handle_webhook(webhook_event({"object": "instagram", "entry": [{"messaging": [{"read": {"mid": "x"}}]}]}), verify_token="test-token", repository=store, publisher=publisher, profile_tokens=ProfileTokens(), graph=ProfileGraph())
        third = handle_webhook(webhook_event({"object": "page", "entry": []}), verify_token="test-token", repository=store, publisher=publisher, profile_tokens=ProfileTokens(), graph=ProfileGraph())
        self.assertEqual((first["statusCode"], second["statusCode"], third["statusCode"]), (200, 200, 200))
        self.assertEqual(store.messages, {})
        self.assertEqual(publisher.jobs, [])

    def test_attachment_only_message_does_not_crash(self):
        store, publisher = InboundStore(), Publisher()
        body = instagram_message()
        body["entry"][0]["messaging"][0]["message"] = {"mid": "attachment-mid", "attachments": [{"type": "image"}]}
        result = handle_webhook(webhook_event(body), verify_token="test-token", repository=store, publisher=publisher, profile_tokens=ProfileTokens(), graph=ProfileGraph())
        self.assertEqual(result["statusCode"], 200)
        self.assertIsNone(store.messages["attachment-mid"]["text"])

    def test_new_follower_username_is_enriched(self):
        store, publisher = InboundStore(username=None, existing=False), Publisher()
        tokens, graph = ProfileTokens(), ProfileGraph()
        result = handle_webhook(webhook_event(instagram_message()), verify_token="",
                                repository=store, publisher=publisher, profile_tokens=tokens, graph=graph)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(store.username, "new_handle")
        self.assertEqual(store.username_updates, [(FOLLOWER_ID, "new_handle")])
        self.assertEqual(tokens.account_ids, ["creator-ig-id"])
        self.assertEqual(graph.calls, [(tokens.token, "creator-ig-id", "follower-ig-id")])
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])

    def test_existing_follower_with_null_username_is_enriched(self):
        store, publisher = InboundStore(username=None, existing=True), Publisher()
        result = handle_webhook(webhook_event(instagram_message()), verify_token="",
                                repository=store, publisher=publisher,
                                profile_tokens=ProfileTokens(), graph=ProfileGraph())
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(store.username, "new_handle")
        self.assertEqual(store.follower_calls, 1)

    def test_existing_username_skips_profile_lookup(self):
        store, publisher = InboundStore(username="known_handle"), Publisher()
        tokens, graph = ProfileTokens(), ProfileGraph()
        result = handle_webhook(webhook_event(instagram_message()), verify_token="",
                                repository=store, publisher=publisher, profile_tokens=tokens, graph=graph)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(tokens.account_ids, [])
        self.assertEqual(graph.calls, [])
        self.assertEqual(store.username_updates, [])
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])

    def test_meta_profile_error_does_not_lose_dm_or_log_token(self):
        store, publisher = InboundStore(username=None), Publisher()
        tokens = ProfileTokens(token="sensitive-token-must-not-appear")
        graph = ProfileGraph(error=RestError(400, 100, "OAuthException"))
        with self.assertLogs("webhook", level="INFO") as logs:
            result = handle_webhook(webhook_event(instagram_message()), verify_token="",
                                    repository=store, publisher=publisher, profile_tokens=tokens, graph=graph)
        self.assertEqual(result["statusCode"], 200)
        self.assertIsNone(store.username)
        self.assertEqual(len(store.messages), 1)
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])
        output = "\n".join(logs.output)
        self.assertIn("phase=meta_profile_lookup", output)
        self.assertIn("http_status=400", output)
        self.assertNotIn(tokens.token, output)

    def test_profile_without_username_does_not_block_inbound(self):
        store, publisher = InboundStore(username=None), Publisher()
        graph = ProfileGraph(profile={"id": "follower-ig-id", "username": None, "name": "A name"})
        result = handle_webhook(webhook_event(instagram_message()), verify_token="",
                                repository=store, publisher=publisher,
                                profile_tokens=ProfileTokens(), graph=graph)
        self.assertEqual(result["statusCode"], 200)
        self.assertIsNone(store.username)
        self.assertEqual(store.username_updates, [])
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])

    def test_missing_profile_token_does_not_block_inbound(self):
        store, publisher = InboundStore(username=None), Publisher()
        graph = ProfileGraph()
        result = handle_webhook(webhook_event(instagram_message()), verify_token="",
                                repository=store, publisher=publisher,
                                profile_tokens=ProfileTokens(token=None), graph=graph)
        self.assertEqual(result["statusCode"], 200)
        self.assertIsNone(store.username)
        self.assertEqual(graph.calls, [])
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])

    def test_unmapped_or_invalid_profile_does_not_change_username(self):
        profiles = [{"id": "another-follower", "username": "wrong_handle"},
                    {"username": "unmapped_handle"},
                    {"id": "follower-ig-id", "username": " A display name "},
                    {"id": "follower-ig-id", "username": ""}]
        for profile in profiles:
            with self.subTest(profile=profile):
                store, publisher = InboundStore(username=None), Publisher()
                result = handle_webhook(webhook_event(instagram_message()), verify_token="",
                                        repository=store, publisher=publisher,
                                        profile_tokens=ProfileTokens(), graph=ProfileGraph(profile=profile))
                self.assertEqual(result["statusCode"], 200)
                self.assertIsNone(store.username)
                self.assertEqual(store.username_updates, [])
                self.assertEqual(len(store.messages), 1)
                self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])

    def test_every_message_persists_and_publishes_before_enrichment(self):
        store, publisher = InboundStore(username=None), Publisher()
        test = self

        class CheckingGraph(ProfileGraph):
            def user_profile(self, *args):
                test.assertEqual(len(store.messages), 2)
                test.assertEqual(len(publisher.jobs), 2)
                return super().user_profile(*args)

        graph = CheckingGraph()
        body = instagram_message()
        second = instagram_message()["entry"][0]["messaging"][0]
        second["message"]["mid"] = "meta-mid-2"
        body["entry"][0]["messaging"].append(second)
        result = handle_webhook(webhook_event(body), verify_token="",
                                repository=store, publisher=publisher,
                                profile_tokens=ProfileTokens(), graph=graph)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(store.username, "new_handle")
        self.assertEqual(len(graph.calls), 1)

    def test_low_lambda_time_budget_skips_enrichment_after_ingestion(self):
        store, publisher = InboundStore(username=None), Publisher()
        tokens, graph = ProfileTokens(), ProfileGraph()
        result = handle_webhook(webhook_event(instagram_message()), verify_token="",
                                repository=store, publisher=publisher,
                                profile_tokens=tokens, graph=graph,
                                remaining_time_ms=lambda: 11999)
        self.assertEqual(result["statusCode"], 200)
        self.assertIsNone(store.username)
        self.assertEqual(tokens.account_ids, [])
        self.assertEqual(graph.calls, [])
        self.assertEqual(len(store.messages), 1)
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])

    def test_credential_error_does_not_block_or_leak_secrets(self):
        class FailingTokens:
            def for_account(self, account_id):
                raise RuntimeError("private-credential-error")

        store, publisher = InboundStore(username=None), Publisher()
        with self.assertLogs("webhook", level="INFO") as logs:
            result = handle_webhook(webhook_event(instagram_message()), verify_token="",
                                    repository=store, publisher=publisher,
                                    profile_tokens=FailingTokens(), graph=ProfileGraph())
        self.assertEqual(result["statusCode"], 200)
        self.assertIsNone(store.username)
        self.assertEqual(len(store.messages), 1)
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])
        self.assertNotIn("private-credential-error", "\n".join(logs.output))

    def test_username_update_error_does_not_block_inbound(self):
        class FailingUpdateStore(InboundStore):
            def update_follower_username_if_missing(self, follower_id, username):
                raise RestError(503, "database_unavailable")

        store, publisher = FailingUpdateStore(username=None), Publisher()
        result = handle_webhook(webhook_event(instagram_message()), verify_token="",
                                repository=store, publisher=publisher,
                                profile_tokens=ProfileTokens(), graph=ProfileGraph())
        self.assertEqual(result["statusCode"], 200)
        self.assertIsNone(store.username)
        self.assertEqual(len(store.messages), 1)
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID)])


class OutboundStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.outbound = {}
        self.insert_count = 0
        self.updated = []

    def get_inbound(self, message_id):
        return {"id": message_id, "follower_id": FOLLOWER_ID}

    def get_follower(self, follower_id):
        return {"id": follower_id, "ig_scoped_id": "follower-ig-id", "creator_id": CREATOR_ID}

    def get_creator_by_profile(self, profile_id):
        return {"id": CREATOR_ID} if profile_id == "signed-in-user" else None

    def get_ig_account(self, creator_id):
        return {"id": ACCOUNT_ID, "creator_id": creator_id, "ig_user_id": "17841479724216495"}

    def create_outbound(self, row):
        with self.lock:
            if row["client_request_id"] in self.outbound:
                raise DuplicateRequest()
            self.insert_count += 1
            value = {"id": "outbound-id", **row}
            self.outbound[row["client_request_id"]] = value
            return value

    def get_outbound_by_client_request_id(self, request_id):
        return self.outbound.get(request_id)

    def update_outbound(self, outbound_id, *, status, meta_message_id=None, attempts=None):
        with self.lock:
            row = self.outbound[REQUEST_ID]
            row.update(status=status, meta_message_id=meta_message_id)
            if attempts is not None:
                row["attempts"] = attempts
            self.updated.append(status)
            return row.copy()


class Auth:
    def user_id(self, jwt):
        return "signed-in-user" if jwt == "user-jwt" else None


class Graph:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail
        self.lock = threading.Lock()

    def validate_send_account(self, token, account_id):
        pass

    def send(self, token, account_id, recipient, text):
        with self.lock:
            self.calls += 1
        if self.fail:
            raise RuntimeError("provider failure")
        return "meta-message-id"


class BlockingGraph(Graph):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def validate_send_account(self, token, account_id):
        pass

    def send(self, token, account_id, recipient, text):
        with self.lock:
            self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("test timed out")
        return "meta-message-id"


def send_event(request_id=REQUEST_ID):
    return {"httpMethod": "POST", "headers": {"Authorization": "Bearer user-jwt"}, "body": json.dumps({
        "inbound_message_id": MESSAGE_ID, "text": "A manual reply", "client_request_id": request_id,
    })}


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.store, self.graph = OutboundStore(), Graph()
        self.deps = {"auth": Auth(), "repository": self.store, "profile_tokens": ProfileTokens(), "graph": self.graph}

    def test_duplicate_client_request_id_never_sends_again(self):
        first = handle_send(send_event(), **self.deps)
        second = handle_send(send_event(), **self.deps)
        self.assertEqual((first["statusCode"], second["statusCode"]), (200, 200))
        self.assertEqual(self.store.insert_count, 1)
        self.assertEqual(self.graph.calls, 1)
        self.assertEqual(json.loads(second["body"])["status"], "sent")

    def test_concurrent_duplicate_has_one_winner(self):
        self.graph = BlockingGraph()
        self.deps["graph"] = self.graph
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(handle_send, send_event(), **self.deps)
            self.assertTrue(self.graph.started.wait(timeout=2))
            second = pool.submit(handle_send, send_event(), **self.deps)
            duplicate = second.result(timeout=2)
            self.graph.release.set()
            winner = first.result(timeout=2)
        results = [winner, duplicate]
        self.assertEqual([r["statusCode"] for r in results], [200, 200])
        self.assertEqual(self.store.insert_count, 1)
        self.assertEqual(self.graph.calls, 1)

    def test_meta_failure_marks_reserved_row_failed(self):
        self.graph.fail = True
        result = handle_send(send_event(), **self.deps)
        self.assertEqual(result["statusCode"], 502)
        self.assertEqual(self.store.updated, ["pending", "failed"])
        self.assertEqual(self.store.outbound[REQUEST_ID]["status"], "failed")

    def test_unauthenticated_request_never_reserves_or_sends(self):
        event = send_event()
        event["headers"] = {}
        result = handle_send(event, **self.deps)
        self.assertEqual(result["statusCode"], 401)
        self.assertEqual(self.store.insert_count, 0)
        self.assertEqual(self.graph.calls, 0)

    def test_valid_reply_records_attempt_before_send(self):
        test = self
        class CheckedGraph(Graph):
            def send(inner, token, account_id, recipient, text):
                row = test.store.outbound[REQUEST_ID]
                test.assertEqual((row["status"], row["attempts"]), ("pending", 1))
                test.assertEqual((token, account_id, recipient),
                                 ("private-test-token", "17841479724216495", "follower-ig-id"))
                return super().send(token, account_id, recipient, text)
        self.deps["graph"] = CheckedGraph()
        result = handle_send(send_event(), **self.deps)
        self.assertEqual(result["statusCode"], 200)
        row = self.store.outbound[REQUEST_ID]
        self.assertEqual((row["status"], row["meta_message_id"], row["attempts"]),
                         ("sent", "meta-message-id", 1))
        self.assertEqual(self.deps["profile_tokens"].account_ids, ["17841479724216495"])

    def test_invalid_jwt_rejected(self):
        event = send_event()
        event["headers"]["Authorization"] = "Bearer invalid-jwt"
        self.assertEqual(handle_send(event, **self.deps)["statusCode"], 401)
        self.assertEqual(self.graph.calls, 0)
        self.assertEqual(self.store.insert_count, 0)

    def test_other_creator_rejected_even_with_spoofed_browser_ids(self):
        self.store.get_follower = lambda _: {"id": FOLLOWER_ID, "creator_id": "another-creator"}
        event = send_event()
        data = json.loads(event["body"])
        data.update(creator_id=CREATOR_ID, follower_id=FOLLOWER_ID, ig_account_id=ACCOUNT_ID)
        event["body"] = json.dumps(data)
        self.assertEqual(handle_send(event, **self.deps)["statusCode"], 403)
        self.assertEqual(self.graph.calls, 0)
        self.assertEqual(self.store.insert_count, 0)

    def test_missing_inbound_rejected(self):
        self.store.get_inbound = lambda _: None
        self.assertEqual(handle_send(send_event(), **self.deps)["statusCode"], 404)
        self.assertEqual(self.store.insert_count, 0)

    def test_ambiguous_account_rejected(self):
        self.store.get_ig_account = lambda _: None
        self.assertEqual(handle_send(send_event(), **self.deps)["statusCode"], 409)
        self.assertEqual(self.graph.calls, 0)

    def test_invalid_text_and_ids_rejected_before_reservation(self):
        for fields in ({"text": " "}, {"text": "a" * 1000}, {"text": "😀" * 251},
                       {"client_request_id": "bad"}, {"inbound_message_id": "bad"}):
            with self.subTest(fields=fields):
                event = send_event()
                data = json.loads(event["body"])
                data.update(fields)
                event["body"] = json.dumps(data)
                self.assertEqual(handle_send(event, **self.deps)["statusCode"], 400)
        self.assertEqual(self.store.insert_count, 0)
        self.assertEqual(self.graph.calls, 0)

    def test_same_request_id_with_different_reply_rejected(self):
        handle_send(send_event(), **self.deps)
        event = send_event()
        data = json.loads(event["body"])
        data["text"] = "Different reply"
        event["body"] = json.dumps(data)
        self.assertEqual(handle_send(event, **self.deps)["statusCode"], 409)
        self.assertEqual(self.graph.calls, 1)

    def test_failed_meta_duplicate_never_retries_send(self):
        self.graph.fail = True
        self.assertEqual(handle_send(send_event(), **self.deps)["statusCode"], 502)
        duplicate = handle_send(send_event(), **self.deps)
        self.assertEqual(json.loads(duplicate["body"])["status"], "failed")
        self.assertEqual(self.graph.calls, 1)

    def test_credential_failure_safe_and_no_send(self):
        class FailingTokens:
            def for_account(self, account_id):
                raise RuntimeError("private-credential-value")
        self.deps["profile_tokens"] = FailingTokens()
        with self.assertLogs("sender", level="INFO") as logs:
            result = handle_send(send_event(), **self.deps)
        self.assertEqual(result["statusCode"], 502)
        self.assertNotIn("private-credential-value", "\n".join(logs.output) + result["body"])
        self.assertEqual(self.store.outbound[REQUEST_ID]["attempts"], 0)
        self.assertEqual(self.graph.calls, 0)

    def test_token_identity_mismatch_never_sends(self):
        def reject(*args):
            raise ValueError("wrong account")
        self.graph.validate_send_account = reject
        self.assertEqual(handle_send(send_event(), **self.deps)["statusCode"], 502)
        self.assertEqual(self.graph.calls, 0)
        self.assertEqual(self.store.outbound[REQUEST_ID]["attempts"], 0)

    def test_status_update_failure_does_not_repeat_meta(self):
        original = self.store.update_outbound
        def fail_sent(*args, **kwargs):
            if kwargs["status"] == "sent":
                raise RestError(503, "unavailable")
            return original(*args, **kwargs)
        self.store.update_outbound = fail_sent
        result = handle_send(send_event(), **self.deps)
        self.assertEqual(result["statusCode"], 503)
        self.assertEqual(json.loads(result["body"])["status"], "pending")
        handle_send(send_event(), **self.deps)
        self.assertEqual(self.graph.calls, 1)

    def test_transient_status_update_retried_without_resending(self):
        original = self.store.update_outbound
        failures = []
        def fail_once(*args, **kwargs):
            if kwargs["status"] == "sent" and not failures:
                failures.append(True)
                raise RestError(503, "unavailable")
            return original(*args, **kwargs)
        self.store.update_outbound = fail_once
        self.assertEqual(handle_send(send_event(), **self.deps)["statusCode"], 200)
        self.assertEqual(self.graph.calls, 1)


if __name__ == "__main__":
    unittest.main()
