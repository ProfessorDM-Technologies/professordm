"""Unit tests for the draft eval in eval/eval_draft.py.

Covers the automatic checks (draft._check on the rebuilt reply, bytes and
refs), the coverage label scored for no_draft, the judge's model choice,
settings and message, the recording search wrapper, the gate sweep and pick,
and the summary metrics. Every fixture uses made-up text; the model calls
are fakes, so nothing touches the network. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

EVAL = Path(__file__).resolve().parents[3] / "eval"
sys.path.insert(0, str(EVAL))

import eval_draft  # noqa: E402  (needs the sys.path line above)
import draft  # noqa: E402
import llm  # noqa: E402

ANSWER = "Pale new growth is often a light clue. Check how many hours of bright light it gets."


def passage(n, similarity=0.6, hpa="HPA-TEST-0001"):
    """Build one search result with made-up text."""
    return {"entry_id": f"entry-{n}", "doc_id": "doc-1", "hpa_id": hpa, "source": "doc",
            "title": f"Test Guide > Section {n}", "content": f"Made-up passage {n}.", "similarity": similarity,
            "score": similarity}


def drafted(answer=ANSWER, cited=("entry-1",), coverage="high", model="anthropic/claude-sonnet-5.5", flags=()):
    """Build a drafted decision citing the given entry ids."""
    return {"status": "drafted", "reason": None, "knowledge_coverage": coverage, "missing_info": [],
            "draft": {"ai_text": answer, "used_web_search": False,
                      "citations": [{"kind": "knowledge", "ref": e, "title": "T", "hpa_id": "HPA-TEST-0001",
                                     "supports": "light"} for e in cited]},
            "safety_flags": list(flags), "model": model, "prompt_version": "draft-v1+test", "retrieved": []}


def no_draft(reason, coverage="none"):
    """Build a no_draft decision."""
    return {"status": "no_draft", "reason": reason, "knowledge_coverage": coverage, "missing_info": [],
            "draft": None, "safety_flags": [], "model": None, "prompt_version": "draft-v1+test", "retrieved": []}


def golden(row_id="draft-001", kind="plain", coverage="high", expected=("HPA-TEST-0001",), channel="instagram",
           split="dev", **extra):
    """Build one golden row with made-up text."""
    return {"id": row_id, "split": split, "kind": kind, "channel": channel,
            "question_text": "Why is my made-up fern pale?", "safety_flagged": False,
            "expected_hpa_ids": list(expected), "expected_coverage": coverage, "notes": "", **extra}


def scored(row, decision, passages=(passage(1),), judge=None):
    """Score a row without calling the judge, then attach a canned verdict."""
    out = eval_draft.score(row, decision, list(passages), [], 100, None, judge=False)
    out["judge"] = judge
    return out


class CheckTests(unittest.TestCase):
    def test_valid_draft_passes(self):
        checks = eval_draft.check(drafted(), [passage(1), passage(2)], "instagram")
        self.assertEqual(checks, {"validator": None, "bytes": len(ANSWER), "bytes_ok": True, "refs_ok": True,
                                  "passed": True})

    def test_citation_of_unsent_passage_fails(self):
        checks = eval_draft.check(drafted(cited=("entry-9",)), [passage(1)], "instagram")
        self.assertEqual(checks["validator"], "unknown_ref")
        self.assertFalse(checks["refs_ok"])
        self.assertFalse(checks["passed"])

    def test_no_citations_fails(self):
        checks = eval_draft.check(drafted(cited=()), [passage(1)], "instagram")
        self.assertEqual(checks["validator"], "no_sources")
        self.assertFalse(checks["refs_ok"])

    def test_byte_limit_is_per_channel(self):
        long = "é" * 600  # 1200 bytes: over Instagram's 1000, under the app's 4000
        self.assertEqual(eval_draft.check(drafted(long), [passage(1)], "instagram")["validator"], "too_long")
        self.assertFalse(eval_draft.check(drafted(long), [passage(1)], "instagram")["bytes_ok"])
        self.assertTrue(eval_draft.check(drafted(long), [passage(1)], "knowledge_app")["passed"])

    def test_uses_draft_validators(self):
        for answer, code in [("Use **bright** light.", "markdown"), ("See www.example.test", "url"),
                             ("As the passage says, water less.", "banned_word"), ("Per [K1], water less.", "ref_marker")]:
            self.assertEqual(eval_draft.check(drafted(answer), [passage(1)], "instagram")["validator"], code)

    def test_risk_flags_become_risk_topics(self):
        flags = [{"layer": "policy", "category": "risk_topic", "detail": "not a profile topic"}]
        self.assertEqual(eval_draft.check(drafted(flags=flags), [passage(1)], "instagram")["validator"],
                         "bad_risk_topic")


class LabelAndJudgeTests(unittest.TestCase):
    def test_no_draft_scores_as_none(self):
        self.assertEqual(eval_draft.got_coverage(no_draft("safety_blocked", coverage="high")), "none")
        self.assertEqual(eval_draft.got_coverage(drafted(coverage="partial")), "partial")

    def test_judge_is_never_the_drafting_family(self):
        self.assertEqual(eval_draft.judge_model(drafted(model="anthropic/claude-sonnet-5.5")), eval_draft.JUDGE_MODEL)
        self.assertEqual(eval_draft.judge_model(drafted(model="openai/gpt-5.6-terra")),
                         eval_draft.JUDGE_MODEL_FOR_OPENAI)
        self.assertEqual(eval_draft.judge_model(drafted(model=None)), eval_draft.JUDGE_MODEL)

    def test_judge_message_has_all_passages_rounds_and_sources(self):
        rounds = [{"round": 2, "prompt": "How long?", "reply": "Two weeks"},
                  {"round": 1, "prompt": "Which plant?", "reply": "A made-up fern"}]
        row = golden(kind="clarified", original_text="help", rounds=rounds)
        message = eval_draft.judge_message(row, drafted(cited=("entry-2",)), [passage(1), passage(2)])
        self.assertIn('[K1] "Test Guide > Section 1"', message)
        self.assertIn('[K2] "Test Guide > Section 2"', message)
        self.assertLess(message.index("Round 1 reply"), message.index("Round 2 reply"))
        self.assertIn('Original message:\n"help"', message)
        self.assertIn('K2: "light"', message)
        self.assertIn(json.dumps(ANSWER), message)

    def test_judge_settings_per_model(self):
        calls = []

        def fake_openrouter(system, user, schema, **options):
            """Record the call and return a grounded verdict."""
            calls.append(options)
            return json.dumps({"grounded": True, "unsupported_claims": [], "uses_clarification": False}), {
                "model": options["model"], "cost": 0.01}

        with patch.object(llm, "_openrouter", fake_openrouter):
            sol = eval_draft.run_judge(golden(), drafted(), [passage(1)])
            gemini = eval_draft.run_judge(golden(), drafted(model="openai/gpt-5.6-terra"), [passage(1)])
        self.assertEqual(calls[0]["model"], "openai/gpt-6.1-sol")
        self.assertIsNone(calls[0]["temperature"])
        self.assertEqual(calls[1]["model"], "google/gemini-2.5-pro")
        self.assertEqual(calls[1]["temperature"], 0)
        self.assertTrue(sol["grounded"])
        self.assertEqual(gemini["unsupported_claims"], [])
        self.assertIsNone(sol["error"])

    def test_judge_bad_reply_is_an_error_not_a_verdict(self):
        with patch.object(llm, "_openrouter", lambda *a, **k: ("not json", {"model": "m", "cost": 0})):
            verdict = eval_draft.run_judge(golden(), drafted(), [passage(1)])
        self.assertEqual(verdict["error"], "not_json")
        self.assertIsNone(verdict["grounded"])


class SearchAndRunTests(unittest.TestCase):
    def test_search_wrapper_records_and_passes_settings(self):
        seen = []

        def base(query, creator, **options):
            """Record the options and return two passages."""
            seen.append(options)
            return [passage(1), passage(2)]

        embed = object()
        search = eval_draft.make_search(base, exclude_tags=["review:pending"], embed=embed)
        eval_draft._row.searches = []
        results = search("q", "creator-a", k=8, sources=["doc"])
        self.assertEqual(seen[0], {"candidates": 20, "per_doc": 3, "k": 8, "sources": ["doc"],
                                   "exclude_tags": ["review:pending"], "embed": embed})
        self.assertEqual(eval_draft._row.searches, [results])

    def test_run_draft_passes_row_fields_and_returns_passages(self):
        received = {}

        def fake_draft(question, **kwargs):
            """Record the arguments, run the search once and decline at the gate."""
            received.update(kwargs, question=question)
            kwargs["search"]("q", kwargs["creator_id"], k=8, sources=["doc"])
            return no_draft("no_coverage")

        search = eval_draft.make_search(lambda q, c, **o: [passage(1, 0.1)], exclude_tags=[], embed=None)
        row = golden(kind="risk", safety_flagged=True, flagged_topics=["a topic"])
        with patch.object(draft, "draft", fake_draft):
            decision, passages, metas, _, error = eval_draft.run_draft(row, "creator-a", search)
        self.assertEqual(decision["reason"], "no_coverage")
        self.assertEqual([p["entry_id"] for p in passages], ["entry-1"])
        self.assertIsNone(error)
        self.assertEqual((received["channel"], received["flagged_topics"], received["time_left"]),
                         ("instagram", ["a topic"], None))

    def test_run_draft_stops_on_a_non_transient_error(self):
        def failing(question, **kwargs):
            """Fail like a bad key."""
            raise llm.LLMError("openrouter", 401, "auth")

        with patch.object(draft, "draft", failing):
            decision, _, _, _, error = eval_draft.run_draft(golden(), "creator-a", None)
        self.assertIsNone(decision)
        self.assertIn("401", error)

    def test_recording_write_draft_keeps_meta(self):
        wrapped = eval_draft._recording_write_draft(lambda *a, **k: ({"answer": ""}, {"attempt": "fallback"}))
        eval_draft._row.metas = []
        wrapped("s", "u", {})
        self.assertEqual(eval_draft._row.metas, [{"attempt": "fallback"}])


class SweepAndSummaryTests(unittest.TestCase):
    def test_sweep_counts_and_pick(self):
        rows = [scored(golden("a", coverage="none", expected=()), no_draft("no_coverage"), [passage(1, 0.22)]),
                scored(golden("b", coverage="none", expected=()), no_draft("no_coverage"), [passage(1, 0.33)]),
                scored(golden("c"), no_draft("no_coverage"), [passage(1, 0.31)]),
                scored(golden("d"), no_draft("no_coverage"), [passage(1, 0.45)])]
        table, pick = eval_draft.sweep(rows)
        at = {row["cutoff"]: row for row in table}
        self.assertEqual((at[0.25]["stopped"], at[0.25]["wrongly_stopped"]), (1, 0))
        self.assertEqual((at[0.35]["stopped"], at[0.35]["wrongly_stopped"]), (2, 1))
        self.assertEqual((at[0.5]["stopped"], at[0.5]["wrongly_stopped"]), (2, 2))
        # 0.35 to 0.45 all stop both out-of-KB rows with one answerable row stopped; the lowest wins.
        self.assertEqual(pick, 0.35)

    def test_sweep_steps(self):
        self.assertEqual(eval_draft.SWEEP[0], 0.2)
        self.assertEqual(eval_draft.SWEEP[-1], 0.5)
        self.assertEqual(len(eval_draft.SWEEP), 13)

    def test_p90(self):
        self.assertEqual(eval_draft.p90(list(range(1, 11))), 9)
        self.assertEqual(eval_draft.p90([5]), 5)
        self.assertIsNone(eval_draft.p90([]))

    def test_summary_metrics(self):
        grounded = {"grounded": True, "uses_clarification": True, "unsupported_claims": [], "cost": 0.01,
                    "error": None}
        rows = [scored(golden("a", kind="out_of_kb", coverage="none", expected=()), no_draft("no_coverage")),
                scored(golden("b", kind="out_of_kb", coverage="none", expected=()), drafted(coverage="partial"),
                       judge={**grounded, "grounded": False, "unsupported_claims": ["x"]}),
                scored(golden("c", kind="clarified"), drafted(), judge=grounded),
                scored(golden("d", coverage="partial"), no_draft("invalid_output"),
                       [passage(1, hpa="HPA-OTHER-0001")])]
        rows.append({**rows[0], "id": "e", "status": "error", "coverage": None})
        s = eval_draft.summarize(rows)
        self.assertEqual((s["n"], s["errors"], s["drafted"]), (5, 1, 2))
        self.assertEqual(s["no_draft"]["no_coverage"], 1)
        self.assertEqual(s["no_draft"]["invalid_output"], 1)
        self.assertEqual(s["coverage"]["correct"], 2)
        self.assertEqual(s["coverage"]["confusion"]["none"]["partial"], 1)
        self.assertEqual(s["coverage"]["confusion"]["partial"]["none"], 1)
        self.assertEqual((s["abstention"]["hits"], s["abstention"]["n"]), (1, 2))
        self.assertEqual((s["false_abstention"]["hits"], s["false_abstention"]["n"]), (1, 2))
        self.assertEqual((s["grounded"]["hits"], s["grounded"]["n"]), (1, 2))
        self.assertEqual((s["uses_clarification"]["hits"], s["uses_clarification"]["n"]), (1, 1))
        self.assertEqual((s["retrieval_hit"]["hits"], s["retrieval_hit"]["n"]), (1, 2))
        self.assertEqual(s["checks"]["rate"], 1.0)
        self.assertAlmostEqual(s["cost"]["judge_total"], 0.02)


if __name__ == "__main__":
    unittest.main()
