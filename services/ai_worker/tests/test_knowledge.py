"""Unit tests for knowledge.py.

No test touches the network: search() gets FakeEmbed, and either FakeRpc or,
for the default Supabase client, a patched knowledge.urlopen (FakeUrlopen)
that records the request and returns or raises a queued outcome. The
environment is replaced per test, so a real .env never leaks in. Every
fixture uses made-up text. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import json
import os
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "eval"))

import kb_eval_common  # noqa: E402  (needs the sys.path lines above)
import knowledge  # noqa: E402
import llm  # noqa: E402


ENV = {"SUPABASE_URL": "https://example.supabase.co/", "SUPABASE_SERVICE_ROLE_KEY": "test-service-key"}
VECTOR = [0.1, 0.2, 0.3]
QUERY = "made-up question about pale new growth"
RESULT_KEYS = {"entry_id", "doc_id", "hpa_id", "source", "title", "content", "similarity", "score"}


def row(entry_id, similarity=0.5, *, doc_id="doc-1", hpa="HPA-TEST-0001", tags=None, source="doc", score=0.03):
    """Build one match_knowledge result row with an hpa tag unless tags are given."""
    return {"id": entry_id, "doc_id": doc_id, "question_id": None, "source": source, "title": f"Guide > {entry_id}",
            "content": "made-up passage text", "tags": tags if tags is not None else [f"hpa:{hpa}", "kind:section"],
            "similarity": similarity, "score": score}


class FakeEmbed:
    """Stand-in for llm.embed: records each call's texts and options and returns VECTOR per text."""

    def __init__(self):
        """Start with no calls."""
        self.calls = []

    def __call__(self, texts, **options):
        """Record the call and return one vector per text plus a meta dict."""
        self.calls.append((list(texts), options))
        return [VECTOR for _ in texts], {"model": "fake", "tokens": 3, "latency_ms": 1}


class FakeRpc:
    """Stand-in for the rpc callable: records each body and returns the given rows (or raises them)."""

    def __init__(self, rows):
        """Store the rows to return, or an exception to raise."""
        self.rows = rows
        self.bodies = []

    def __call__(self, body):
        """Record the body and return (or raise) the configured outcome."""
        self.bodies.append(body)
        if isinstance(self.rows, Exception):
            raise self.rows
        return self.rows


class FakeResponse:
    """A minimal urlopen response: a context manager whose read() returns JSON bytes."""

    def __init__(self, payload):
        """Store the payload to serve."""
        self.payload = payload

    def __enter__(self):
        """Return itself, like the real response."""
        return self

    def __exit__(self, *exc):
        """Close nothing; never swallow exceptions."""
        return False

    def read(self):
        """Return the payload as JSON bytes."""
        return json.dumps(self.payload).encode("utf-8")


class FakeUrlopen:
    """Stand-in for knowledge.urlopen: records the Request and timeout, then returns or raises the outcome."""

    def __init__(self, outcome):
        """Store a payload to return as a response, or an exception to raise."""
        self.outcome = outcome
        self.requests = []

    def __call__(self, request, timeout=None):
        """Record the request and return a FakeResponse (or raise the configured error)."""
        self.requests.append((request, timeout))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return FakeResponse(self.outcome)


def search(rows=(), env=None, **kwargs):
    """Run knowledge.search with FakeEmbed and FakeRpc under a controlled environment; return (results, rpc, embed)."""
    rpc, embed = FakeRpc(list(rows) if isinstance(rows, (list, tuple)) else rows), FakeEmbed()
    with patch.dict(os.environ, env if env is not None else ENV, clear=True):
        return knowledge.search(QUERY, "creator-a", rpc=rpc, embed=embed, **kwargs), rpc, embed


class RequestTests(unittest.TestCase):
    """The default Supabase client sends the right URL, headers and body, and maps errors to LLMError."""

    def call(self, outcome, env=ENV, **kwargs):
        """Run search with the default rpc and a FakeUrlopen; return (results or error, fake urlopen)."""
        fake = FakeUrlopen(outcome)
        # assertLogs captures the PASS or FAIL line so test output stays clean.
        with patch.dict(os.environ, env, clear=True), patch.object(knowledge, "urlopen", fake), \
                self.assertLogs("knowledge", "INFO"):
            try:
                return knowledge.search(QUERY, "creator-a", embed=FakeEmbed(), **kwargs), fake
            except (llm.LLMError, RuntimeError) as error:
                return error, fake

    def test_request_url_headers_and_body(self):
        """One POST to /rest/v1/rpc/match_knowledge with the service key headers, a 10 s timeout and every body field."""
        results, fake = self.call([row("e1")], sources=["doc"], published_only=True, candidates=12,
                                  exclude_tags=["review:pending"])
        self.assertEqual(len(results), 1)
        (request, timeout), = fake.requests
        self.assertEqual(request.full_url, "https://example.supabase.co/rest/v1/rpc/match_knowledge")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Apikey"), "test-service-key")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-service-key")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(timeout, knowledge.SUPABASE_TIMEOUT)
        self.assertEqual(timeout, 10)
        self.assertEqual(json.loads(request.data), {
            "query_embedding": VECTOR, "query_text": QUERY, "p_creator_id": "creator-a", "match_count": 12,
            "p_sources": ["doc"], "p_published_only": True, "p_exclude_tags": ["review:pending"]})

    def test_defaults_in_body(self):
        """Without options the body asks for 20 candidates, all sources, unpublished too and no excluded tags."""
        _, fake = self.call([])
        body = json.loads(fake.requests[0][0].data)
        self.assertEqual((body["match_count"], body["p_sources"], body["p_published_only"], body["p_exclude_tags"]),
                         (20, None, False, None))

    def test_http_500_raises_llm_error_with_postgrest_code_only(self):
        """An HTTP error becomes LLMError("supabase", status, code), keeping the PostgREST code and never its message."""
        body = BytesIO(json.dumps({"code": "XX000", "message": "secret made-up detail", "details": None}).encode())
        error, _ = self.call(HTTPError("https://example.supabase.co", 500, "Server Error", {}, body))
        self.assertIsInstance(error, llm.LLMError)
        self.assertEqual((error.service, error.status, error.code), ("supabase", 500, "XX000"))
        self.assertNotIn("secret", str(error))

    def test_http_error_without_json_body(self):
        """An HTTP error with an unreadable body still raises, with no code."""
        error, _ = self.call(HTTPError("https://example.supabase.co", 503, "Unavailable", {}, BytesIO(b"<html>")))
        self.assertEqual((error.service, error.status, error.code), ("supabase", 503, None))

    def test_network_error_raises_llm_error(self):
        """A network failure becomes LLMError("supabase", None, exception name)."""
        error, _ = self.call(URLError("down"))
        self.assertEqual((error.service, error.status, error.code), ("supabase", None, "URLError"))

    def test_response_that_is_not_a_list_raises_bad_response(self):
        """A response that is not a list of rows is an outage, never an empty result."""
        error, _ = self.call({"rows": []})
        self.assertEqual((error.service, error.code), ("supabase", "bad_response"))

    def test_missing_env_raises_runtime_error_naming_the_variable(self):
        """A missing setting raises RuntimeError naming it, before any embedding or request."""
        for missing in ENV:
            with self.subTest(missing=missing):
                embed, fake = FakeEmbed(), FakeUrlopen([])
                env = {name: value for name, value in ENV.items() if name != missing}
                with patch.dict(os.environ, env, clear=True), patch.object(knowledge, "urlopen", fake):
                    with self.assertRaises(RuntimeError) as caught:
                        knowledge.search(QUERY, "creator-a", embed=embed)
                self.assertEqual(str(caught.exception), f"Missing {missing}")
                self.assertEqual((embed.calls, fake.requests), ([], []))


class ExcludeTagTests(unittest.TestCase):
    """exclude_tags=None reads KB_EXCLUDE_TAGS; any explicit list, even [], wins."""

    def exclude(self, env_value=None, **kwargs):
        """Return the p_exclude_tags sent for a given KB_EXCLUDE_TAGS value (None leaves it unset)."""
        env = {**ENV, **({} if env_value is None else {"KB_EXCLUDE_TAGS": env_value})}
        _, rpc, _ = search(env=env, **kwargs)
        return rpc.bodies[0]["p_exclude_tags"]

    def test_env_is_split_trimmed_and_empties_dropped(self):
        """Comma-separated tags are trimmed and empty items dropped."""
        self.assertEqual(self.exclude(" review:pending , ,kind:card,"), ["review:pending", "kind:card"])

    def test_empty_or_unset_env_means_none(self):
        """An unset, empty or comma-only variable sends null (exclude nothing)."""
        for value in (None, "", "  ", " , ,"):
            with self.subTest(value=value):
                self.assertIsNone(self.exclude(value))

    def test_explicit_list_overrides_env(self):
        """An explicit list is sent as is, whatever the variable says."""
        self.assertEqual(self.exclude("review:pending", exclude_tags=["kind:card"]), ["kind:card"])

    def test_explicit_empty_list_means_exclude_nothing(self):
        """exclude_tags=[] is sent as [] and never falls back to the variable."""
        self.assertEqual(self.exclude("review:pending", exclude_tags=[]), [])


class ResultTests(unittest.TestCase):
    """Rows are capped per guide, trimmed to k and mapped to the result shape."""

    def test_per_doc_cap_keeps_order(self):
        """At most per_doc rows per doc_id, in RPC order."""
        rows = [row("a1"), row("a2"), row("b1", doc_id="doc-2"), row("a3"), row("a4"), row("b2", doc_id="doc-2")]
        results, _, _ = search(rows)
        self.assertEqual([r["entry_id"] for r in results], ["a1", "a2", "b1", "a3", "b2"])
        results, _, _ = search(rows, per_doc=1)
        self.assertEqual([r["entry_id"] for r in results], ["a1", "b1"])

    def test_null_doc_id_rows_are_each_their_own_group(self):
        """Rows with a null doc_id are never capped together."""
        rows = [{**row(f"q{i}", doc_id=None, source="question"), "tags": None} for i in range(4)] + [row("a1"), row("a2")]
        results, _, _ = search(rows, per_doc=1)
        self.assertEqual([r["entry_id"] for r in results], ["q0", "q1", "q2", "q3", "a1"])

    def test_top_k_after_the_cap(self):
        """k trims the capped list, so a capped row never takes a slot."""
        rows = [row("a1"), row("a2"), row("a3"), row("b1", doc_id="doc-2"), row("c1", doc_id="doc-3")]
        results, _, _ = search(rows, k=3, per_doc=1)
        self.assertEqual([r["entry_id"] for r in results], ["a1", "b1", "c1"])
        results, _, _ = search([row(f"x{i}", doc_id=f"d{i}") for i in range(12)])
        self.assertEqual(len(results), 8)

    def test_result_shape(self):
        """Each result has exactly the documented keys, with the row's values."""
        results, _, _ = search([row("e1", 0.71, score=0.032)])
        self.assertEqual(results, [{"entry_id": "e1", "doc_id": "doc-1", "hpa_id": "HPA-TEST-0001", "source": "doc",
                                    "title": "Guide > e1", "content": "made-up passage text",
                                    "similarity": 0.71, "score": 0.032}])

    def test_hpa_id_from_the_first_hpa_tag(self):
        """hpa_id is the first hpa: tag's value, or None without one or with null tags."""
        rows = [row("e1", tags=["kind:section", "hpa:HPA-TEST-0002", "hpa:HPA-TEST-0003"]),
                row("e2", doc_id="doc-2", tags=["kind:card", "topic:light"]),
                {**row("e3", doc_id=None), "tags": None}]
        results, _, _ = search(rows)
        self.assertEqual([r["hpa_id"] for r in results], ["HPA-TEST-0002", None, None])

    def test_empty_results(self):
        """No rows from the RPC gives an empty list."""
        results, _, _ = search([])
        self.assertEqual(results, [])

    def test_same_shape_as_offline_search(self):
        """The eval's offline_search returns the same keys, so the evals score both modes alike."""
        offline = kb_eval_common.offline_search(
            "q", "creator-a", embed=lambda texts: ([[1.0, 0.0] for _ in texts], {}),
            rows=[{"id": "e1", "creator_id": "creator-a", "doc_id": "doc-1", "source": "doc", "title": "t",
                   "content": "c", "tags": ["hpa:HPA-TEST-0001"], "embedding": [1.0, 0.0]}])
        live, _, _ = search([row("e1")])
        self.assertEqual(set(offline[0]), RESULT_KEYS)
        self.assertEqual(set(live[0]), RESULT_KEYS)

    def test_rpc_error_propagates(self):
        """An LLMError from the rpc is raised, never turned into empty results."""
        with self.assertRaises(llm.LLMError), self.assertLogs("knowledge", "WARNING"):
            search(llm.LLMError("supabase", 500, "XX000"))


class EmbedTests(unittest.TestCase):
    """The query is embedded once, fail-fast, with llm.embed resolved at call time."""

    def test_embed_called_once_with_one_input_fail_fast(self):
        """embed gets exactly [query_text] and retry=False, once."""
        _, _, embed = search([row("e1")])
        self.assertEqual(embed.calls, [([QUERY], {"retry": False})])

    def test_default_embed_is_llm_embed_at_call_time(self):
        """With embed=None, a patched llm.embed is the one called."""
        fake, rpc = FakeEmbed(), FakeRpc([])
        with patch.dict(os.environ, ENV, clear=True), patch.object(llm, "embed", fake):
            knowledge.search(QUERY, "creator-a", rpc=rpc)
        self.assertEqual(fake.calls, [([QUERY], {"retry": False})])
        self.assertEqual(rpc.bodies[0]["query_embedding"], VECTOR)


class LogTests(unittest.TestCase):
    """The log line carries counts, the best similarity and latency, never text."""

    def test_log_line_has_counts_but_no_text(self):
        """No query, title or passage text reaches the log; counts and the best similarity do."""
        with self.assertLogs("knowledge", level="INFO") as logs:
            search([row("e1", 0.61), row("e2", 0.42)])
        output = "\n".join(logs.output)
        self.assertIn("results=2", output)
        self.assertIn("best_similarity=0.610", output)
        for text in (QUERY, "made-up passage text", "Guide >", "test-service-key"):
            self.assertNotIn(text, output)

    def test_failure_logs_status_and_code(self):
        """A Supabase failure logs a warning with the status and code only."""
        with self.assertLogs("knowledge", level="WARNING") as logs, self.assertRaises(llm.LLMError):
            search(llm.LLMError("supabase", 500, "XX000"))
        self.assertIn("status=500 error=XX000", "\n".join(logs.output))
        self.assertNotIn(QUERY, "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
