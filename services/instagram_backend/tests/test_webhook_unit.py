"""Unit tests for webhook helper functions - API Testing competency demo."""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webhook import _response, _raw_body, _messages, handle_webhook


# --- _response ---

def test_response_sets_status_code():
    r = _response(200, "OK")
    assert r["statusCode"] == 200

def test_response_sets_body():
    r = _response(400, "Bad Request")
    assert r["body"] == "Bad Request"

def test_response_empty_body_default():
    r = _response(200)
    assert r["body"] == ""

def test_response_content_type_header():
    r = _response(200)
    assert r["headers"]["Content-Type"] == "text/plain"


# --- _raw_body ---

def test_raw_body_plain_string():
    event = {"body": '{"key": "value"}', "isBase64Encoded": False}
    assert _raw_body(event) == b'{"key": "value"}'

def test_raw_body_base64_encoded():
    payload = b"hello world"
    event = {"body": base64.b64encode(payload).decode(), "isBase64Encoded": True}
    assert _raw_body(event) == payload

def test_raw_body_missing_body_defaults_empty():
    event = {}
    assert _raw_body(event) == b""

def test_raw_body_invalid_base64_raises():
    event = {"body": "not-valid-base64!!!", "isBase64Encoded": True}
    try:
        _raw_body(event)
        assert False, "Expected ValueError"
    except ValueError:
        pass


# --- _messages ---

def _make_event(recipient="page-id", sender="user-id", mid="msg-1", text="hi"):
    return {
        "object": "instagram",
        "entry": [{"messaging": [{
            "sender": {"id": sender},
            "recipient": {"id": recipient},
            "message": {"mid": mid, "text": text},
        }]}],
    }

def test_messages_yields_correct_fields():
    msgs = list(_messages(_make_event()))
    assert len(msgs) == 1
    mid, sender_id, recipient_id, text = msgs[0]
    assert mid == "msg-1"
    assert sender_id == "user-id"
    assert recipient_id == "page-id"
    assert text == "hi"

def test_messages_wrong_object_yields_nothing():
    payload = {"object": "whatsapp", "entry": []}
    assert list(_messages(payload)) == []

def test_messages_missing_text_yields_none():
    payload = _make_event()
    payload["entry"][0]["messaging"][0]["message"].pop("text")
    mid, _, _, text = list(_messages(payload))[0]
    assert text is None

def test_messages_non_dict_payload_raises():
    try:
        list(_messages("not a dict"))
        assert False, "Expected ValueError"
    except ValueError:
        pass


# --- handle_webhook GET verification ---

class _Stub:
    def __getattr__(self, _): return lambda *a, **kw: None

def _get_event(mode="subscribe", token="secret", challenge="abc"):
    return {
        "httpMethod": "GET",
        "queryStringParameters": {
            "hub.mode": mode,
            "hub.verify_token": token,
            "hub.challenge": challenge,
        },
    }

def test_webhook_get_valid_verification():
    r = handle_webhook(_get_event(), verify_token="secret",
                       repository=_Stub(), publisher=_Stub(),
                       profile_tokens=_Stub(), graph=_Stub())
    assert r["statusCode"] == 200
    assert r["body"] == "abc"

def test_webhook_get_wrong_token_returns_403():
    r = handle_webhook(_get_event(token="wrong"), verify_token="secret",
                       repository=_Stub(), publisher=_Stub(),
                       profile_tokens=_Stub(), graph=_Stub())
    assert r["statusCode"] == 403

def test_webhook_unsupported_method_returns_405():
    r = handle_webhook({"httpMethod": "DELETE"}, verify_token="secret",
                       repository=_Stub(), publisher=_Stub(),
                       profile_tokens=_Stub(), graph=_Stub())
    assert r["statusCode"] == 405

def test_webhook_post_invalid_json_returns_400():
    r = handle_webhook({"httpMethod": "POST", "body": "not-json"},
                       verify_token="secret", repository=_Stub(),
                       publisher=_Stub(), profile_tokens=_Stub(), graph=_Stub())
    assert r["statusCode"] == 400


if __name__ == "__main__":
    import unittest
    unittest.main(module=__name__, argv=[""], verbosity=2, exit=False)

