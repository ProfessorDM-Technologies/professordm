import base64
import hashlib
import hmac
import json
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sender import DuplicateRequest, handle_send
from webhook import handle_webhook


MESSAGE_ID = "11111111-1111-4111-8111-111111111111"
FOLLOWER_ID = "22222222-2222-4222-8222-222222222222"
CREATOR_ID = "33333333-3333-4333-8333-333333333333"
ACCOUNT_ID = "44444444-4444-4444-8444-444444444444"
REQUEST_ID = "55555555-5555-4555-8555-555555555555"


def webhook_event(body, *, signed=True, encoded=False):
    raw = json.dumps(body, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(b"test-app-secret", raw, hashlib.sha256).hexdigest()
    return {
        "httpMethod": "POST",
        "headers": {"X-Hub-Signature-256": signature if signed else "sha256=bad"},
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
    def __init__(self, known=True):
        self.known = known
        self.messages = {}
        self.follower_calls = 0

    def find_account_by_ig_user_id(self, recipient):
        return {"id": ACCOUNT_ID, "creator_id": CREATOR_ID} if self.known else None

    def upsert_follower(self, creator_id, sender_id, received_at):
        self.follower_calls += 1
        return {"id": FOLLOWER_ID}

    def upsert_inbound(self, mid, follower_id, text):
        self.messages.setdefault(mid, {"id": MESSAGE_ID, "follower_id": follower_id, "text": text})
        return self.messages[mid]


class Publisher:
    def __init__(self):
        self.jobs = []

    def publish(self, message_id, creator_id):
        self.jobs.append((message_id, creator_id))


class WebhookTests(unittest.TestCase):
    def test_verification_get_accepts_only_matching_token(self):
        store, publisher = InboundStore(), Publisher()
        event = {"httpMethod": "GET", "queryStringParameters": {
            "hub.mode": "subscribe", "hub.verify_token": "test-token", "hub.challenge": "challenge-123",
        }}
        good = handle_webhook(event, verify_token="test-token", app_secret="test-app-secret", repository=store, publisher=publisher)
        bad = handle_webhook(event, verify_token="wrong", app_secret="test-app-secret", repository=store, publisher=publisher)
        self.assertEqual((good["statusCode"], good["body"]), (200, "challenge-123"))
        self.assertEqual(bad["statusCode"], 403)

    def test_bad_signature_never_writes_or_publishes(self):
        store, publisher = InboundStore(), Publisher()
        with self.assertLogs("webhook", level="WARNING") as logs:
            result = handle_webhook(webhook_event(instagram_message(), signed=False), verify_token="test-token", app_secret="test-app-secret", repository=store, publisher=publisher)
        self.assertEqual(result["statusCode"], 401)
        self.assertEqual(store.follower_calls, 0)
        self.assertEqual(store.messages, {})
        self.assertEqual(publisher.jobs, [])
        self.assertIn("sha256_present=True", logs.output[0])
        self.assertNotIn("sha256=bad", logs.output[0])

    def test_duplicate_mid_creates_one_row_and_uses_stable_job_identity(self):
        store, publisher = InboundStore(), Publisher()
        event = webhook_event(instagram_message(), encoded=True)
        for _ in range(2):
            result = handle_webhook(event, verify_token="test-token", app_secret="test-app-secret", repository=store, publisher=publisher)
            self.assertEqual(result["statusCode"], 200)
        self.assertEqual(len(store.messages), 1)
        self.assertEqual(publisher.jobs, [(MESSAGE_ID, CREATOR_ID), (MESSAGE_ID, CREATOR_ID)])

    def test_unknown_recipient_and_unsupported_event_do_not_write(self):
        store, publisher = InboundStore(known=False), Publisher()
        first = handle_webhook(webhook_event(instagram_message()), verify_token="test-token", app_secret="test-app-secret", repository=store, publisher=publisher)
        second = handle_webhook(webhook_event({"object": "instagram", "entry": [{"messaging": [{"read": {"mid": "x"}}]}]}), verify_token="test-token", app_secret="test-app-secret", repository=store, publisher=publisher)
        third = handle_webhook(webhook_event({"object": "page", "entry": []}), verify_token="test-token", app_secret="test-app-secret", repository=store, publisher=publisher)
        self.assertEqual((first["statusCode"], second["statusCode"], third["statusCode"]), (200, 200, 200))
        self.assertEqual(store.messages, {})
        self.assertEqual(publisher.jobs, [])

    def test_attachment_only_message_does_not_crash(self):
        store, publisher = InboundStore(), Publisher()
        body = instagram_message()
        body["entry"][0]["messaging"][0]["message"] = {"mid": "attachment-mid", "attachments": [{"type": "image"}]}
        result = handle_webhook(webhook_event(body), verify_token="test-token", app_secret="test-app-secret", repository=store, publisher=publisher)
        self.assertEqual(result["statusCode"], 200)
        self.assertIsNone(store.messages["attachment-mid"]["text"])


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
        return {"id": ACCOUNT_ID, "creator_id": creator_id, "vault_token_id": "vault-id"}

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

    def update_outbound(self, outbound_id, *, status, meta_message_id=None):
        with self.lock:
            row = self.outbound[REQUEST_ID]
            row.update(status=status, meta_message_id=meta_message_id)
            self.updated.append(status)
            return row.copy()


class Auth:
    def user_id(self, jwt):
        return "signed-in-user" if jwt == "user-jwt" else None


class Vault:
    def page_token(self, account_id):
        return "test-page-token"


class Graph:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail
        self.lock = threading.Lock()

    def send(self, token, recipient, text):
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

    def send(self, token, recipient, text):
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
        self.deps = {"auth": Auth(), "repository": self.store, "vault": Vault(), "graph": self.graph}

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
        self.assertEqual(self.store.updated, ["failed"])
        self.assertEqual(self.store.outbound[REQUEST_ID]["status"], "failed")

    def test_unauthenticated_request_never_reserves_or_sends(self):
        event = send_event()
        event["headers"] = {}
        result = handle_send(event, **self.deps)
        self.assertEqual(result["statusCode"], 401)
        self.assertEqual(self.store.insert_count, 0)
        self.assertEqual(self.graph.calls, 0)


if __name__ == "__main__":
    unittest.main()
