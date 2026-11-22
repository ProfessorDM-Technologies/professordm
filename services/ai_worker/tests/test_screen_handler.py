"""Unit tests for screen_handler.py (the Lambda entry of the final answer screen).

No test calls a real model or AWS: llm.moderate and llm.check_answer_rules are
replaced by fakes, and boto3 is a fake module whose SSM client returns made-up
values. Every fixture uses made-up text. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import hashlib
import json
import os
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm  # noqa: E402  (needs the sys.path line above)
import screen_handler  # noqa: E402
from prompts import SWEETLIFE_FLORA  # noqa: E402


CREATOR = "11111111-2222-4333-8444-555555555555"
TEXT = "A made-up reply about moving a fern closer to the window."
QUESTION = "A made-up question about a pale fern?"
CONTRACT_KEYS = {"decision", "next_actor", "reason_codes", "categories", "rules", "flags", "text_sha256",
                 "check_version", "model", "latency_ms"}
INVALID = {"error": "invalid_request"}
SSM_NAMES = {"SSM_OPENAI_KEY": "/test/openai-key", "SSM_OPENROUTER_KEY": "/test/openrouter-key"}


def payload(**fields):
    """Build a valid request payload, with the given fields replaced."""
    return {"text": TEXT, "creator_id": CREATOR, "channel": "instagram", "question_text": QUESTION,
            "trace_id": "trace-1", **fields}


def without(key):
    """Build a valid payload with one key removed."""
    event = payload()
    del event[key]
    return event


class FakeSsm:
    """Stand-in for the boto3 SSM client: records each get_parameter call and returns a made-up value."""

    def __init__(self):
        """Start with no calls."""
        self.calls = []

    def get_parameter(self, Name, WithDecryption):  # noqa: N803  (boto3's argument names)
        """Record the call and return "secret-<name>" as the value."""
        self.calls.append((Name, WithDecryption))
        return {"Parameter": {"Value": f"secret-{Name}"}}


def fake_boto3(ssm):
    """Build a fake boto3 module whose client("ssm") is the given fake."""
    module = types.ModuleType("boto3")
    module.client = lambda service: ssm
    return module


class FakeChecks:
    """Stand-ins for llm.moderate and llm.check_answer_rules that record what they were given."""

    def __init__(self, hits=None, broken=(), topics=()):
        """Store the moderation hits and the rules result to return."""
        self.hits = dict(hits or {})
        self.broken, self.topics = list(broken), list(topics)
        self.moderated = []
        self.checked = []
        self.keys_seen = []

    def moderate(self, text):
        """Record the text and the OpenAI key in the environment, then return the hits."""
        self.moderated.append(text)
        self.keys_seen.append(os.environ.get("OPENAI_API_KEY"))
        return self.hits

    def check_answer_rules(self, text, question_text, profile, *, timeout):
        """Record the call and the OpenRouter key in the environment, then return the rules result."""
        self.checked.append({"text": text, "question_text": question_text, "profile": profile, "timeout": timeout})
        self.keys_seen.append(os.environ.get("OPENROUTER_API_KEY"))
        return {"broken_rules": self.broken, "risk_topics": self.topics, "model": "served/model",
                "latency_ms": 5, "prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0001}


class HandlerTestCase(unittest.TestCase):
    """Shared setup: a clean secrets cache, a fake SSM, and an environment without the two keys."""

    def setUp(self):
        """Reset the per-container cache and patch the environment and boto3 for one test."""
        screen_handler._load_secrets.cache_clear()
        self.addCleanup(screen_handler._load_secrets.cache_clear)
        environment = patch.dict(os.environ, SSM_NAMES)
        environment.start()
        self.addCleanup(environment.stop)
        for variable in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
            os.environ.pop(variable, None)
        self.ssm = FakeSsm()
        modules = patch.dict(sys.modules, {"boto3": fake_boto3(self.ssm)})
        modules.start()
        self.addCleanup(modules.stop)

    def handle(self, event, checks=None):
        """Call the handler with fake model calls; return (response, every log line, the fakes)."""
        checks = checks or FakeChecks()
        with patch.object(llm, "moderate", checks.moderate), \
                patch.object(llm, "check_answer_rules", checks.check_answer_rules), \
                self.assertLogs(level="INFO") as logs:
            response = screen_handler.lambda_handler(event, None)
        return response, logs.output, checks


class ValidationTests(HandlerTestCase):
    """A payload that breaks the contract gets invalid_request before any secret is loaded or model called."""

    def test_invalid_payloads(self):
        """Every broken payload returns exactly {"error": "invalid_request"} and touches nothing else."""
        cases = (
            ("missing text", without("text"), "text"),
            ("empty text", payload(text=""), "text"),
            ("text over 4000", payload(text="a" * 4001), "text"),
            ("text not a string", payload(text=7), "text"),
            ("text is null", payload(text=None), "text"),
            ("unencodable text", payload(text="broken \ud83d"), "text"),
            ("bad channel", payload(channel="email"), "channel"),
            ("missing channel", without("channel"), "channel"),
            ("channel not a string", payload(channel=["instagram"]), "channel"),
            ("bad uuid", payload(creator_id="not-a-uuid"), "creator_id"),
            ("uuid without hyphens", payload(creator_id=CREATOR.replace("-", "")), "creator_id"),
            ("uuid with trailing text", payload(creator_id=CREATOR + "\n"), "creator_id"),
            ("missing creator", without("creator_id"), "creator_id"),
            ("creator not a string", payload(creator_id=5), "creator_id"),
            ("question not a string", payload(question_text=["x"]), "question_text"),
            ("unencodable question", payload(question_text="broken \ud83d"), "question_text"),
            ("trace id not a string", payload(trace_id=5), "trace_id"),
            ("event is a string", "text", "event"),
            ("event is a list", [], "event"),
            ("event is None", None, "event"),
        )
        for name, event, field in cases:
            with self.subTest(name=name):
                response, logs, checks = self.handle(event)
                self.assertEqual(response, INVALID)
                self.assertEqual((checks.moderated, checks.checked, self.ssm.calls), ([], [], []))
                self.assertEqual(len(logs), 1)
                self.assertIn(f"Final screen invalid_request field={field}", logs[0])

    def test_boundaries_are_valid(self):
        """The edges of the contract are accepted: 1 and 4000 characters, both channels, optional fields."""
        emoji = "🌿" * 4000  # 4000 characters, 16000 bytes: the limit is in characters
        for name, event in (
                ("4000 characters", payload(text="a" * 4000)),
                ("4000 emoji", payload(text=emoji)),
                ("a single space", payload(text=" ")),
                ("knowledge_app", payload(channel="knowledge_app")),
                ("question null", payload(question_text=None)),
                ("question absent", without("question_text")),
                ("trace id null", payload(trace_id=None)),
                ("trace id absent", without("trace_id")),
                ("unknown extra key", payload(client_request_id="abc")),
                ("upper-case uuid", payload(creator_id=CREATOR.upper()))):
            with self.subTest(name=name):
                response, _, _ = self.handle(event)
                self.assertEqual(set(response), CONTRACT_KEYS)
                self.assertEqual(response["decision"], "PASS")

    def test_invalid_request_log_holds_no_payload_values(self):
        """The invalid_request line names the field and nothing from the payload."""
        _, logs, _ = self.handle(payload(channel="secret channel value", text="secret reply text",
                                         question_text="secret question text"))
        self.assertEqual(len(logs), 1)
        self.assertNotIn("secret", logs[0])


class ResponseTests(HandlerTestCase):
    """A valid payload returns the contract's response with every key present."""

    def test_valid_payload_returns_every_contract_key(self):
        """All ten keys, the hash of the exact text, an integer latency, and JSON-serializable."""
        text = "  a made-up reply with spaces around it \n"
        response, _, _ = self.handle(payload(text=text))
        self.assertEqual(set(response), CONTRACT_KEYS)
        self.assertEqual((response["decision"], response["next_actor"]), ("PASS", "none"))
        self.assertEqual(response["text_sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(response["check_version"], "final-check-v1+sweetlife-v2")
        self.assertEqual(response["model"], "served/model")
        self.assertIsInstance(response["latency_ms"], int)
        self.assertGreaterEqual(response["latency_ms"], 0)
        self.assertEqual(json.loads(json.dumps(response)), response)

    def test_exact_text_question_and_profile_reach_the_checks(self):
        """Both checks see the text unchanged; the rules check also gets the question and the profile."""
        text = "  a made-up reply with spaces around it \n"
        _, _, checks = self.handle(payload(text=text))
        self.assertEqual(checks.moderated, [text])
        self.assertEqual(checks.checked, [{"text": text, "question_text": QUESTION, "profile": SWEETLIFE_FLORA,
                                           "timeout": llm.TIMEOUT}])

    def test_missing_or_empty_question_is_passed_as_none(self):
        """A manual reply has no question: null, absent and "" all reach the check as None."""
        for event in (payload(question_text=None), without("question_text"), payload(question_text="")):
            with self.subTest(event=event.get("question_text", "absent")):
                _, _, checks = self.handle(event)
                self.assertIsNone(checks.checked[0]["question_text"])

    def test_broken_rule_maps_to_hold(self):
        """A broken answer rule comes back as HOLD for the creator, with the rule id and text."""
        response, _, _ = self.handle(payload(), FakeChecks(broken=["R2"]))
        self.assertEqual((response["decision"], response["next_actor"]), ("HOLD", "creator"))
        self.assertEqual(response["reason_codes"], ["answer_rule"])
        self.assertEqual(response["rules"], [{"id": "R2", "text": SWEETLIFE_FLORA["answer_rules"][1]}])
        self.assertEqual(response["flags"], [{"layer": "policy", "category": "answer_rule", "detail": "R2"}])

    def test_blocked_term_maps_to_block(self):
        """A blocked phrase comes back as BLOCK."""
        response, _, _ = self.handle(payload(text="ok kys then"))
        self.assertEqual((response["decision"], response["next_actor"]), ("BLOCK", "creator"))
        self.assertEqual(response["categories"], ["blocked_term"])


class SecretsTests(HandlerTestCase):
    """The two model keys come from SSM once per container, and nothing else is read."""

    def test_secrets_load_once_per_container(self):
        """Two requests make one SSM call per key, decrypted, and the checks find both keys in the environment."""
        _, _, first = self.handle(payload())
        self.handle(payload())
        self.assertEqual(self.ssm.calls, [("/test/openai-key", True), ("/test/openrouter-key", True)])
        self.assertEqual(sorted(first.keys_seen), ["secret-/test/openai-key", "secret-/test/openrouter-key"])

    def test_supabase_is_never_read(self):
        """This function needs no database: only the OpenAI and OpenRouter keys are listed and loaded."""
        self.assertEqual(screen_handler.SECRETS, (("OPENAI_API_KEY", "SSM_OPENAI_KEY"),
                                                  ("OPENROUTER_API_KEY", "SSM_OPENROUTER_KEY")))
        self.handle(payload())
        self.assertFalse(any("supabase" in name.lower() for name, _ in self.ssm.calls))

    def test_failed_secret_load_gives_check_unavailable(self):
        """Without the keys the real calls refuse to start: HOLD for the system, no request, a config error line."""
        for variable in SSM_NAMES:
            del os.environ[variable]
        requests = []
        with patch.object(llm, "_json_request", lambda *args, **kwargs: requests.append(args)), \
                self.assertLogs(level="INFO") as logs:
            response = screen_handler.lambda_handler(payload(), None)
        self.assertEqual(requests, [])
        self.assertEqual(set(response), CONTRACT_KEYS)
        self.assertEqual((response["decision"], response["next_actor"]), ("HOLD", "system"))
        self.assertEqual(response["reason_codes"], ["check_unavailable"])
        self.assertIsNone(response["model"])
        self.assertTrue(any("Final screen config_error error_type=RuntimeError" in line for line in logs.output))

    def test_failed_secret_load_is_not_cached(self):
        """A failed load is tried again on the next request, so a fixed configuration recovers by itself."""
        names = {variable: os.environ.pop(variable) for variable in SSM_NAMES}
        response, _, _ = self.handle(payload())
        self.assertEqual(self.ssm.calls, [])
        self.assertEqual(set(response), CONTRACT_KEYS)
        os.environ.update(names)
        self.handle(payload())
        self.assertEqual(len(self.ssm.calls), 2)

    def test_empty_ssm_value_is_a_config_error(self):
        """A parameter with no value is a failed load, not an empty key."""
        self.ssm.get_parameter = lambda Name, WithDecryption: {"Parameter": {"Value": ""}}  # noqa: N803
        _, logs, _ = self.handle(payload())
        self.assertTrue(any("Final screen config_error error_type=RuntimeError" in line for line in logs))
        self.assertNotIn("OPENAI_API_KEY", os.environ)


class LogTests(HandlerTestCase):
    """One summary line per call, with metadata only."""

    def test_one_summary_line_with_the_fields(self):
        """The summary line carries the decision, the findings, counts, latency, trace id and version."""
        _, logs, _ = self.handle(payload(), FakeChecks({"harassment": 0.7}, broken=["R2"]))
        lines = [line for line in logs if line.startswith("INFO:screen_handler:")]
        self.assertEqual(len(lines), 1)
        for part in ("Final screen decision=HOLD next_actor=creator reasons=moderation_mild,answer_rule "
                     "categories=harassment rules=R2 flags=2 ", f"text_chars={len(TEXT)} ",
                     f"question_chars={len(QUESTION)} ", "channel=instagram ", "model=served/model ",
                     "latency_ms=", "check_version=final-check-v1+sweetlife-v2 ", "trace_id=trace-1"):
            self.assertIn(part, lines[0])

    def test_empty_values_print_as_none(self):
        """A clean manual reply with no trace id logs none for each empty field."""
        _, logs, _ = self.handle({"text": TEXT, "creator_id": CREATOR, "channel": "knowledge_app"})
        line = [line for line in logs if line.startswith("INFO:screen_handler:")][0]
        self.assertIn("decision=PASS next_actor=none reasons=none categories=none rules=none flags=0 ", line)
        self.assertIn("question_chars=0 channel=knowledge_app ", line)
        self.assertTrue(line.endswith("trace_id=none"))

    def test_logs_never_contain_text_question_or_keys(self):
        """No line from any module holds the reply, the question, an SSM value or a key."""
        text, question = "secret reply text about a fern", "secret question text about a fern"
        _, held, _ = self.handle(payload(text=text, question_text=question), FakeChecks({"harassment": 0.7},
                                                                                        broken=["R2"]))
        _, blocked, _ = self.handle(payload(text=text + " kys", question_text=question))
        for variable in SSM_NAMES:
            del os.environ[variable]
        screen_handler._load_secrets.cache_clear()
        _, failed, _ = self.handle(payload(text=text, question_text=question))
        output = "\n".join([*held, *blocked, *failed])
        self.assertNotIn("secret", output)

    def test_trace_id_is_cleaned_for_the_log(self):
        """A caller cannot put text into the log through trace_id: only safe characters, at most 64."""
        _, logs, _ = self.handle(payload(trace_id="my secret text!\n" + "x" * 100))
        line = [line for line in logs if line.startswith("INFO:screen_handler:")][0]
        trace = line.rsplit("trace_id=", 1)[1]
        self.assertRegex(trace, r"^[A-Za-z0-9._:-]{1,64}$")
        self.assertEqual(trace, ("mysecrettext" + "x" * 100)[:64])
        self.assertNotIn("\n", line)
        self.assertEqual(len(re.findall("trace_id=", line)), 1)


if __name__ == "__main__":
    unittest.main()
