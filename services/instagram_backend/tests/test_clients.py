import json
from io import BytesIO
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clients import MetaGraph, RestError, SsmProfileTokens, SupabaseRepository, SupabaseVault, SqsPublisher, _json_request


class FakeRest:
    def __init__(self):
        self.calls = []

    def request(self, method, path, *, params=None, body=None, prefer=None, timeout=8):
        self.calls.append((method, path, params, body, prefer))
        if path == "ig_followers":
            return [{"id": "follower-id"}]
        if path == "inbound_messages":
            return [{"id": "message-id"}]
        if path == "rpc/meta_page_token_for_account":
            return "test-page-token"
        return []


class FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)


class ExistingMidRest(FakeRest):
    def request(self, method, path, *, params=None, body=None, prefer=None):
        self.calls.append((method, path, params, body, prefer))
        if path == "inbound_messages" and method == "POST":
            return []
        if path == "inbound_messages" and method == "GET":
            return [{"id": "existing-id", "follower_id": "first-follower"}]
        return []


class ClientTests(unittest.TestCase):
    def test_follower_and_message_upserts_name_conflict_columns(self):
        rest = FakeRest()
        repo = SupabaseRepository(rest)
        repo.upsert_follower("creator-id", "scoped-id", "2026-10-14T00:00:00+00:00")
        repo.upsert_inbound("meta-mid", "follower-id", "hello")
        self.assertEqual(rest.calls[0][2], {"on_conflict": "ig_scoped_id"})
        self.assertEqual(rest.calls[1][2], {"on_conflict": "mid"})
        self.assertEqual(rest.calls[0][4], "resolution=merge-duplicates,return=representation")
        self.assertEqual(rest.calls[1][4], "resolution=ignore-duplicates,return=representation")

    def test_vault_uses_restricted_rpc_with_account_id(self):
        rest = FakeRest()
        token = SupabaseVault(rest).page_token("account-id")
        self.assertEqual(token, "test-page-token")
        self.assertEqual(rest.calls[0][1:4], ("rpc/meta_page_token_for_account", None, {"p_account_id": "account-id"}))

    def test_duplicate_mid_reads_original_row_without_overwriting_it(self):
        rest = ExistingMidRest()
        inbound = SupabaseRepository(rest).upsert_inbound("meta-mid", "second-follower", "changed text")
        self.assertEqual(inbound, {"id": "existing-id", "follower_id": "first-follower"})
        self.assertEqual([call[0] for call in rest.calls], ["POST", "GET"])

    def test_queue_envelope_matches_shared_contract(self):
        sqs = FakeSqs()
        SqsPublisher(sqs, "https://example.invalid/queue").publish("message-id", "creator-id")
        self.assertEqual(len(sqs.calls), 1)
        job = json.loads(sqs.calls[0]["MessageBody"])
        self.assertEqual(job["type"], "triage")
        self.assertEqual(job["id"], "triage:message-id")
        self.assertEqual(job["payload"], {"messageId": "message-id"})
        self.assertEqual(job["creatorId"], "creator-id")
        self.assertEqual(job["v"], 1)

    def test_username_update_is_conditional_on_null(self):
        rest = FakeRest()
        updated = SupabaseRepository(rest).update_follower_username_if_missing("follower-id", "new_handle")
        self.assertTrue(updated)
        self.assertEqual(rest.calls[0], (
            "PATCH", "ig_followers", {"id": "eq.follower-id", "username": "is.null"},
            {"username": "new_handle"}, "return=representation"))

    def test_instagram_profile_checks_receiving_account_and_sender_identity(self):
        responses = [{"id": "app-scoped-id", "user_id": "17841479724216495"},
                     {"id": "4672837849619460", "username": "handle", "name": "Name"}]
        with patch("clients._json_request", side_effect=responses) as request:
            result = MetaGraph("v26.0").user_profile(
                "private-token", "17841479724216495", "4672837849619460")
        self.assertEqual(result, responses[1])
        self.assertEqual([call.args[0] for call in request.call_args_list], [
            "https://graph.instagram.com/v26.0/me?fields=user_id",
            "https://graph.instagram.com/v26.0/4672837849619460?fields=id%2Cusername%2Cname"])
        for call in request.call_args_list:
            self.assertEqual(call.args[1:], ("GET", {"Authorization": "Bearer private-token"}))
            self.assertEqual(call.kwargs["timeout"], 2)

    def test_wrong_receiving_account_token_never_queries_sender(self):
        for identity in ({"user_id": "999"}, {"id": "17841479724216495"}, None):
            with self.subTest(identity=identity):
                with patch("clients._json_request", return_value=identity) as request:
                    with self.assertRaises(ValueError):
                        MetaGraph("v26.0").user_profile("private-token", "17841479724216495", "4672837849619460")
                self.assertEqual(request.call_count, 1)

    def test_profile_must_identify_exact_webhook_sender(self):
        for profile in ({"id": "999", "username": "wrong_person"},
                        {"username": "unmapped_person"}, [], None):
            with self.subTest(profile=profile):
                with patch("clients._json_request", side_effect=[
                        {"user_id": "17841479724216495"}, profile]):
                    with self.assertRaises(ValueError):
                        MetaGraph("v26.0").user_profile("private-token", "17841479724216495", "4672837849619460")

    def test_profile_credentials_are_scoped_to_receiving_account_and_decrypted(self):
        class Ssm:
            def __init__(self):
                self.calls = []

            def get_parameter(self, **kwargs):
                self.calls.append(kwargs)
                return {"Parameter": {"Value": "private-token"}}

        ssm = Ssm()
        provider = SsmProfileTokens(ssm, "/staging/instagram-profile-tokens/")
        self.assertEqual(provider.for_account("17841479724216495"), "private-token")
        self.assertEqual(ssm.calls, [{
            "Name": "/staging/instagram-profile-tokens/17841479724216495", "WithDecryption": True}])
        self.assertIsNone(SsmProfileTokens(ssm, None).for_account("17841479724216495"))
        with self.assertRaises(ValueError):
            provider.for_account("../different-account")
        self.assertEqual(len(ssm.calls), 1)

    def test_outbound_keeps_existing_facebook_host(self):
        with patch("clients._json_request", return_value={"message_id": "outbound-id"}) as request:
            result = MetaGraph("v26.0").send("private-token", "recipient", "A reply")
        self.assertEqual(result, "outbound-id")
        self.assertEqual(request.call_args.args[0], "https://graph.facebook.com/v26.0/me/messages")

    def test_meta_nested_error_code_and_type_are_available_for_safe_logs(self):
        body = BytesIO(b'{"error":{"message":"Page is not linked","type":"OAuthException","code":100}}')
        error = HTTPError("https://graph.facebook.com/v26.0/1", 400, "Bad Request", {}, body)
        with patch("clients.urlopen", side_effect=error):
            with self.assertRaises(RestError) as raised:
                _json_request("https://graph.facebook.com/v26.0/1", "GET", {})
        self.assertEqual((raised.exception.status, raised.exception.code,
                          raised.exception.error_type), (400, 100, "OAuthException"))


if __name__ == "__main__":
    unittest.main()
