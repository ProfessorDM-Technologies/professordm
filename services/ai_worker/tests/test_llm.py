"""Unit tests for llm.embed(), the _openrouter request options and llm.write_draft().

No test calls the network: llm._json_request is replaced by FakeRequest,
which returns queued responses or raises queued errors, llm._sleep is
replaced so retries never wait, and write_draft gets a FakeClock. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm
from prompts import SWEETLIFE_FLORA


def vector(seed):
    """Build a valid EMBED_DIMENSIONS vector whose first number identifies it."""
    return [float(seed)] + [0.0] * (llm.EMBED_DIMENSIONS - 1)


def response(count, *, order=None, tokens=7, dimensions=llm.EMBED_DIMENSIONS):
    """Build a fake embeddings response for count inputs, items listed in the given index order."""
    order = list(range(count)) if order is None else order
    return {"model": llm.EMBED_MODEL, "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
            "data": [{"index": i, "embedding": [float(i)] + [0.0] * (dimensions - 1)} for i in order]}


class FakeRequest:
    """Stand-in for llm._json_request: records every call and returns or raises queued outcomes."""

    def __init__(self, *outcomes, default=None):
        """Queue outcomes (responses or exceptions); with none left, build a valid response from default."""
        self.outcomes = list(outcomes)
        self.default = default
        self.calls = []

    def __call__(self, service, url, headers, body, timeout=llm.TIMEOUT):
        """Record the call and return (or raise) the next outcome."""
        self.calls.append({"service": service, "url": url, "headers": headers, "body": body, "timeout": timeout})
        outcome = self.outcomes.pop(0) if self.outcomes else self.default(len(body["input"]))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai"})
class EmbedTests(unittest.TestCase):
    def setUp(self):
        """Replace the retry sleep with a recorder, so tests never wait."""
        self.waits = []
        patcher = patch("llm._sleep", side_effect=self.waits.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_vectors_come_back_in_input_order(self):
        """Items returned in shuffled index order are sorted back to input order."""
        fake = FakeRequest(response(4, order=[2, 0, 3, 1]))
        with patch("llm._json_request", fake):
            vectors, _ = llm.embed(["a", "b", "c", "d"])
        self.assertEqual([v[0] for v in vectors], [0.0, 1.0, 2.0, 3.0])

    def test_250_inputs_make_three_requests_and_meta_is_summed(self):
        """Batches of at most 100; vectors from every batch in order; tokens summed."""
        fake = FakeRequest(default=response)
        with patch("llm._json_request", fake):
            vectors, meta = llm.embed([f"text {i}" for i in range(250)])
        self.assertEqual([len(call["body"]["input"]) for call in fake.calls], [100, 100, 50])
        self.assertEqual(fake.calls[2]["body"]["input"][0], "text 200")
        self.assertEqual(len(vectors), 250)
        self.assertEqual(meta["tokens"], 21)
        self.assertEqual(meta["model"], llm.EMBED_MODEL)
        self.assertIsInstance(meta["latency_ms"], int)

    def test_wrong_dimension_raises_bad_dimensions(self):
        """A vector that is not 1536 long is never returned."""
        with patch("llm._json_request", FakeRequest(response(2, dimensions=1535))):
            with self.assertRaises(llm.LLMError) as caught:
                llm.embed(["a", "b"])
        self.assertEqual((caught.exception.service, caught.exception.status, caught.exception.code),
                         ("openai", None, "bad_dimensions"))

    def test_missing_data_raises_bad_response(self):
        """A response without data, or with a missing item, is an outage, not an empty result."""
        for bad in ({"model": llm.EMBED_MODEL}, response(1)):
            with self.subTest(bad=bad.keys()):
                with patch("llm._json_request", FakeRequest(bad)):
                    with self.assertRaises(llm.LLMError) as caught:
                        llm.embed(["a", "b"])
                self.assertEqual(caught.exception.code, "bad_response")

    def test_no_retry_raises_on_first_429(self):
        """Runtime embeds fail fast: one request, no wait."""
        fake = FakeRequest(llm.LLMError("openai", 429, "rate_limit_exceeded"), default=response)
        with patch("llm._json_request", fake):
            with self.assertRaises(llm.LLMError) as caught:
                llm.embed(["a"])
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.waits, [])

    def test_retry_recovers_from_429_and_503(self):
        """With retry=True, a 429 then a 503 are retried with growing waits, then the batch succeeds."""
        fake = FakeRequest(llm.LLMError("openai", 429, None), llm.LLMError("openai", 503, None), default=response)
        with patch("llm._json_request", fake):
            vectors, _ = llm.embed(["a", "b"], retry=True)
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(self.waits, [1, 2])
        self.assertEqual(len(vectors), 2)

    def test_retry_also_covers_network_errors(self):
        """A network error (status None) is retried like a 5xx."""
        fake = FakeRequest(llm.LLMError("openai", None, "TimeoutError"), default=response)
        with patch("llm._json_request", fake):
            llm.embed(["a"], retry=True)
        self.assertEqual(len(fake.calls), 2)

    def test_retry_gives_up_after_five_tries(self):
        """Five failed tries raise the last error, after waits of 1, 2, 4 and 8 seconds."""
        fake = FakeRequest(*[llm.LLMError("openai", 500, None) for _ in range(6)])
        with patch("llm._json_request", fake):
            with self.assertRaises(llm.LLMError) as caught:
                llm.embed(["a"], retry=True)
        self.assertEqual(caught.exception.status, 500)
        self.assertEqual(len(fake.calls), 5)
        self.assertEqual(self.waits, [1, 2, 4, 8])

    def test_400_is_never_retried(self):
        """A client error would fail the same way again, so it raises at once even with retry=True."""
        fake = FakeRequest(llm.LLMError("openai", 400, "invalid_request_error"), default=response)
        with patch("llm._json_request", fake):
            with self.assertRaises(llm.LLMError) as caught:
                llm.embed(["a"], retry=True)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.waits, [])

    def test_request_body_and_headers(self):
        """One OpenAI request to the embeddings URL with the model, the inputs and the key from the environment."""
        fake = FakeRequest(response(2))
        with patch("llm._json_request", fake):
            llm.embed(["first", "second"], timeout=60)
        call = fake.calls[0]
        self.assertEqual(call["service"], "openai")
        self.assertEqual(call["url"], "https://api.openai.com/v1/embeddings")
        self.assertEqual(call["body"], {"model": "text-embedding-3-small", "input": ["first", "second"]})
        self.assertEqual(call["headers"], {"Authorization": "Bearer test-openai",
                                           "Content-Type": "application/json"})
        self.assertEqual(call["timeout"], 60)

    def test_empty_input_makes_no_request(self):
        """Nothing to embed means no call and empty vectors."""
        fake = FakeRequest()
        with patch("llm._json_request", fake):
            vectors, meta = llm.embed([])
        self.assertEqual((vectors, meta["tokens"], fake.calls), ([], 0, []))

    def test_missing_key_raises_before_any_request(self):
        """No OPENAI_API_KEY is a RuntimeError naming the variable, with no request made."""
        fake = FakeRequest(default=response)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), patch("llm._json_request", fake):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                llm.embed(["a"])
        self.assertEqual(fake.calls, [])

    def test_log_line_has_counts_but_no_text(self):
        """The one log line carries batches, inputs and tokens, never the input text."""
        with patch("llm._json_request", FakeRequest(response(1))), self.assertLogs("llm", "INFO") as logs:
            llm.embed(["a secret question about moss"])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("batches=1 inputs=1 tokens=7", logs.output[0])
        self.assertNotIn("moss", logs.output[0])


def chat(content, model="anthropic/claude-sonnet-5.5", *, prompt_tokens=900, completion_tokens=300, cost=0.0072):
    """Build a fake OpenRouter chat completion; model is the one that served it."""
    return {"model": model, "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "cost": cost}}


class FakeClock:
    """Stand-in for time.monotonic: returns the given readings in order, then repeats the last one."""

    def __init__(self, *readings):
        """Store the readings and count how often the clock is read."""
        self.readings = list(readings)
        self.reads = 0

    def __call__(self):
        """Return the next reading."""
        self.reads += 1
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"],
          "additionalProperties": False}
ANSWER = {"answer": "Water when the top inch of soil is dry."}
PRIMARY_PROVIDER = {"data_collection": "deny", "require_parameters": True}


@patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter"})
class OpenRouterTests(unittest.TestCase):
    """_openrouter's new options change only what they should, and every call denies data collection."""
    def call(self, schema=None, **options):
        """Run _openrouter with a fake request; return (content, meta, the recorded call)."""
        fake = FakeRequest(chat("ok", model="served/model"))
        with patch("llm._json_request", fake):
            content, meta = llm._openrouter("system", "user", schema, **options)
        return content, meta, fake.calls[0]

    def test_provider_block_with_and_without_schema(self):
        """data_collection deny is always sent; require_parameters only with a schema."""
        self.assertEqual(self.call()[2]["body"]["provider"], {"data_collection": "deny"})
        self.assertEqual(self.call(SCHEMA)[2]["body"]["provider"], PRIMARY_PROVIDER)

    def test_temperature_left_out_when_none(self):
        """temperature defaults to 0 and is left out of the body entirely when None."""
        self.assertEqual(self.call()[2]["body"]["temperature"], 0)
        self.assertNotIn("temperature", self.call(temperature=None)[2]["body"])

    def test_extra_is_merged_but_cannot_drop_data_collection(self):
        """extra adds top-level body fields; a provider in extra never replaces the deny block."""
        body = self.call(SCHEMA, extra={"reasoning": {"effort": "low"}, "provider": {"sort": "price"}})[2]["body"]
        self.assertEqual(body["reasoning"], {"effort": "low"})
        self.assertEqual(body["provider"], PRIMARY_PROVIDER)

    def test_max_tokens_only_when_given(self):
        """max_tokens is absent by default and sent as given."""
        self.assertNotIn("max_tokens", self.call()[2]["body"])
        self.assertEqual(self.call(max_tokens=2000)[2]["body"]["max_tokens"], 2000)

    def test_model_timeout_and_schema_name(self):
        """model, timeout and schema_name override the triage defaults; no OpenRouter models list is sent."""
        _, _, call = self.call(SCHEMA, model="some/model", timeout=45, schema_name="draft")
        self.assertEqual(call["body"]["model"], "some/model")
        self.assertEqual(call["body"]["response_format"]["json_schema"]["name"], "draft")
        self.assertEqual(call["timeout"], 45)
        self.assertNotIn("models", call["body"])

    def test_meta_model_is_the_served_model(self):
        """meta["model"] is the response's model, not the requested one."""
        content, meta, _ = self.call(model="requested/model")
        self.assertEqual((content, meta["model"]), ("ok", "served/model"))

    def test_triage_bodies_unchanged_apart_from_data_collection(self):
        """classify and write_clarification send the same body as before, plus data_collection deny."""
        valid = {"category": "social", "service_kind": "", "confidence": 0.9, "reason": "Says thanks",
                 "risk_flag": False, "risk_reason": ""}
        fake = FakeRequest(chat(json.dumps(valid)), chat("Which plant is it?"))
        with patch("llm._json_request", fake):
            llm.classify("thanks!", [], SWEETLIFE_FLORA)
            llm.write_clarification("why yellow", [], SWEETLIFE_FLORA)
        classify, clarify = fake.calls
        messages = classify["body"]["messages"]
        self.assertEqual(classify["body"], {
            "model": "google/gemini-3.1-flash-lite", "temperature": 0, "messages": messages,
            "usage": {"include": True},
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "triage", "strict": True, "schema": llm._classify_schema(SWEETLIFE_FLORA)}},
            "provider": PRIMARY_PROVIDER})
        self.assertEqual(clarify["body"], {
            "model": "google/gemini-3.1-flash-lite", "temperature": 0, "messages": clarify["body"]["messages"],
            "usage": {"include": True}, "provider": {"data_collection": "deny"}})
        self.assertEqual([classify["timeout"], clarify["timeout"]], [10, 10])


@patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter"})
class WriteDraftTests(unittest.TestCase):
    """write_draft: primary settings, manual fallback on outages only, deadline rule, JSON and meta."""
    def draft(self, *outcomes, deadline=None, clock=None):
        """Run write_draft against queued outcomes; return (result or raised error, fake request)."""
        fake = FakeRequest(*outcomes)
        # Every path logs at least one draft_call line; capturing them keeps
        # the test output clean (test_logs_carry_usage_but_no_text checks them).
        with patch("llm._json_request", fake), self.assertLogs("llm", "INFO"):
            try:
                result = llm.write_draft("system", "user", SCHEMA, deadline=deadline, clock=clock or FakeClock(0))
            except (llm.LLMError, llm.InvalidOutput) as error:
                result = error
        return result, fake

    def test_primary_request_body(self):
        """The primary is Sonnet 5.5 with no temperature, max_tokens 2000, the strict draft schema and a 45 s timeout."""
        (data, meta), fake = self.draft(chat(json.dumps(ANSWER)))
        self.assertEqual(data, ANSWER)
        self.assertEqual(len(fake.calls), 1)
        body = fake.calls[0]["body"]
        self.assertEqual(body["model"], "anthropic/claude-sonnet-5.5")
        self.assertNotIn("temperature", body)
        self.assertNotIn("reasoning", body)
        self.assertNotIn("models", body)
        self.assertEqual(body["max_tokens"], 2000)
        self.assertEqual(body["response_format"], {"type": "json_schema", "json_schema": {
            "name": "draft", "strict": True, "schema": SCHEMA}})
        self.assertEqual(body["provider"], PRIMARY_PROVIDER)
        self.assertEqual(fake.calls[0]["timeout"], 45)
        self.assertEqual(meta, {"model": "anthropic/claude-sonnet-5.5", "latency_ms": meta["latency_ms"],
                                "prompt_tokens": 900, "completion_tokens": 300, "cost": 0.0072,
                                "attempt": "primary"})

    def test_fallback_on_timeout_429_404_and_5xx(self):
        """Each outage moves to Terra with its own body: no temperature, low reasoning, max_tokens 4000."""
        outages = [llm.LLMError("openrouter", None, "TimeoutError"), llm.LLMError("openrouter", 429, 429),
                   llm.LLMError("openrouter", 404, 404), llm.LLMError("openrouter", 503, 503)]
        for error in outages:
            with self.subTest(status=error.status):
                answer = chat(json.dumps(ANSWER), "openai/gpt-5.6-terra", prompt_tokens=950,
                              completion_tokens=1200, cost=0.004)
                (data, meta), fake = self.draft(error, answer)
                self.assertEqual(data, ANSWER)
                self.assertEqual(len(fake.calls), 2)
                body = fake.calls[1]["body"]
                self.assertEqual(body["model"], "openai/gpt-5.6-terra")
                self.assertNotIn("temperature", body)
                self.assertEqual(body["reasoning"], {"effort": "low"})
                self.assertEqual(body["max_tokens"], 4000)
                self.assertEqual(body["response_format"]["json_schema"]["schema"], SCHEMA)
                self.assertEqual(body["provider"], PRIMARY_PROVIDER)
                self.assertEqual(body["messages"], fake.calls[0]["body"]["messages"])
                self.assertEqual(fake.calls[1]["timeout"], 45)
                self.assertEqual((meta["attempt"], meta["model"], meta["completion_tokens"], meta["cost"]),
                                 ("fallback", "openai/gpt-5.6-terra", 1200, 0.004))

    def test_models_come_from_the_environment_at_call_time(self):
        """DRAFT_MODEL and DRAFT_FALLBACK_MODEL override the defaults when set."""
        with patch.dict(os.environ, {"DRAFT_MODEL": "a/primary", "DRAFT_FALLBACK_MODEL": "b/fallback"}):
            _, fake = self.draft(llm.LLMError("openrouter", 502, None), chat(json.dumps(ANSWER), "b/fallback"))
        self.assertEqual([call["body"]["model"] for call in fake.calls], ["a/primary", "b/fallback"])

    def test_no_fallback_on_client_errors(self):
        """400, 401 and 403 re-raise the primary's error at once, with no fallback call."""
        for status in (400, 401, 403):
            with self.subTest(status=status):
                error, fake = self.draft(llm.LLMError("openrouter", status, "bad"), chat(json.dumps(ANSWER)))
                self.assertIsInstance(error, llm.LLMError)
                self.assertEqual(error.status, status)
                self.assertEqual(len(fake.calls), 1)

    def test_fallback_error_propagates(self):
        """When the fallback fails too, its own error is raised."""
        error, fake = self.draft(llm.LLMError("openrouter", 503, None), llm.LLMError("openrouter", 500, "down"))
        self.assertEqual((error.status, error.code, len(fake.calls)), (500, "down", 2))

    def test_deadline_too_short_before_primary_makes_no_call(self):
        """Under 45 s left raises LLMError("deadline") without a request; exactly 45 s still starts the call."""
        error, fake = self.draft(chat(json.dumps(ANSWER)), deadline=144.9, clock=FakeClock(100))
        self.assertIsInstance(error, llm.LLMError)
        self.assertEqual((error.service, error.status, error.code), ("openrouter", None, "deadline"))
        self.assertEqual(fake.calls, [])
        (_, meta), fake = self.draft(chat(json.dumps(ANSWER)), deadline=145, clock=FakeClock(100))
        self.assertEqual((meta["attempt"], len(fake.calls)), ("primary", 1))

    def test_deadline_too_short_before_fallback_reraises_primary_error(self):
        """If the primary used up the time, its outage is re-raised instead of starting the fallback."""
        clock = FakeClock(0, 20)
        error, fake = self.draft(llm.LLMError("openrouter", 503, "overloaded"), chat(json.dumps(ANSWER)),
                                 deadline=60, clock=clock)
        self.assertEqual((error.status, error.code), (503, "overloaded"))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(clock.reads, 2)

    def test_no_deadline_never_reads_the_clock(self):
        """deadline=None means no limit: the fallback starts and the clock is never read."""
        clock = FakeClock(0)
        (_, meta), _ = self.draft(llm.LLMError("openrouter", None, "URLError"), chat(json.dumps(ANSWER)),
                                  clock=clock)
        self.assertEqual((meta["attempt"], clock.reads), ("fallback", 0))

    def test_not_json_raises_without_fallback(self):
        """A reply that is not a JSON object raises InvalidOutput("not_json") and never tries the fallback."""
        for content in ("Here is your answer", None, json.dumps(["a list"])):
            with self.subTest(content=content):
                error, fake = self.draft(chat(content), chat(json.dumps(ANSWER)))
                self.assertIsInstance(error, llm.InvalidOutput)
                self.assertEqual(error.args, ("not_json",))
                self.assertEqual(len(fake.calls), 1)

    def test_logs_carry_usage_but_no_text(self):
        """Each call logs attempt, served model, tokens and cost or the error, never prompt or answer text."""
        with self.assertLogs("llm", "INFO") as logs:
            fake = FakeRequest(llm.LLMError("openrouter", 429, "rate_limited"),
                               chat(json.dumps({"answer": "secret moss advice"}), "openai/gpt-5.6-terra"))
            with patch("llm._json_request", fake):
                llm.write_draft("secret system prompt", "secret follower question", SCHEMA)
        self.assertEqual(len(logs.output), 2)
        self.assertIn("stage=draft_call FAIL attempt=primary model=anthropic/claude-sonnet-5.5 status=429 "
                      "error=rate_limited", logs.output[0])
        self.assertIn("stage=draft_call PASS attempt=fallback model=openai/gpt-5.6-terra", logs.output[1])
        self.assertIn("prompt_tokens=900 completion_tokens=300 cost=0.0072", logs.output[1])
        self.assertNotIn("secret", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
