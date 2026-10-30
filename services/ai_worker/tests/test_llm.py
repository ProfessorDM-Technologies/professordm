"""Unit tests for llm.embed().

No test calls the network: llm._json_request is replaced by FakeRequest,
which returns queued responses or raises queued errors, and llm._sleep is
replaced so retries never wait. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm


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


if __name__ == "__main__":
    unittest.main()
