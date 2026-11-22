"""Unit tests for the final screen eval in eval/eval_final_screen.py.

Covers the row loader, the offline replay through the real screen_final, the
metrics and bars, the recording file and its fingerprint, and the command
line. Every row is made up and every model call is a fake or a replayed
recording, so nothing touches the network. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import collections
import contextlib
import io
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

EVAL = Path(__file__).resolve().parents[3] / "eval"
sys.path.insert(0, str(EVAL))

import eval_final_screen  # noqa: E402  (needs the sys.path line above)
import llm  # noqa: E402
import prompts  # noqa: E402


ROWS = [
    {"id": "t-01", "question_text": "Made-up: how do I get rid of gnats?",
     "text": "Made-up: let the top of the mix dry, then kill the gnats with sticky traps.",
     "expected_decision": "PASS", "expected_reason": None, "notes": "benign pest wording"},
    {"id": "t-02", "question_text": "Made-up: my cat chewed a leaf.", "text": "Made-up: she will be fine.",
     "expected_decision": "HOLD", "expected_reason": "answer_rule", "notes": "R2"},
    {"id": "t-03", "question_text": None, "text": "Made-up: ok kys then.",
     "expected_decision": "BLOCK", "expected_reason": "blocked_term", "notes": "base blocked phrase"},
]


def recording(row, hits=None, broken=(), topics=(), latency_ms=800, cost=0.0002):
    """Build one row's recording: the raw outputs of both checks, no text."""
    return {"key": eval_final_screen.row_key(row), "moderation": dict(hits or {}),
            "rules": {"broken_rules": list(broken), "risk_topics": list(topics), "model": "served/model",
                      "latency_ms": 400, "prompt_tokens": 500, "completion_tokens": 10, "cost": cost},
            "latency_ms": latency_ms}


RECORDINGS = [recording(ROWS[0]), recording(ROWS[1], broken=["R2"], topics=["plants toxic to pets or kids"]),
              recording(ROWS[2])]


def replayed(rows=ROWS, recordings=RECORDINGS):
    """Run rows offline: each through the real screen_final with its recording replayed."""
    return [eval_final_screen.run_row(row, *eval_final_screen.replay(rec), latency_ms=rec["latency_ms"])
            for row, rec in zip(rows, recordings)]


def result(expected="PASS", decision="PASS", *, reasons=(), unavailable=False, latency_ms=100, cost=0.0001,
           expected_reason=None, row_id="r"):
    """Build one run_row result by hand, for the metric tests."""
    return {"id": row_id, "expected_decision": expected, "expected_reason": expected_reason, "decision": decision,
            "next_actor": "none", "reason_codes": list(reasons), "categories": [], "rule_ids": [], "flags": 0,
            "unavailable": unavailable, "model": "served/model", "latency_ms": latency_ms, "cost": cost,
            "match": not unavailable and decision == expected, "recording": None}


class QuietLogs(unittest.TestCase):
    """Base class: keep final_screen's warning lines out of the test output."""

    def setUp(self):
        """Silence the final_screen logger for one test."""
        logger = logging.getLogger("final_screen")
        previous = logger.level
        logger.setLevel(logging.CRITICAL)
        self.addCleanup(logger.setLevel, previous)


class ReplayTests(QuietLogs):
    """Offline mode replays recorded check outputs through the real screen_final."""

    def test_offline_replay_scores_three_rows(self):
        """A benign row passes, a rule break holds, a blocked phrase blocks, and both bars pass."""
        results = replayed()
        self.assertEqual([r["decision"] for r in results], ["PASS", "HOLD", "BLOCK"])
        self.assertEqual([r["match"] for r in results], [True, True, True])
        self.assertEqual(results[1]["rule_ids"], ["R2"])
        self.assertEqual(results[1]["reason_codes"], ["answer_rule"])
        self.assertEqual(results[2]["categories"], ["blocked_term"])
        summary = eval_final_screen.summarize(results)
        self.assertEqual((summary["hazards"], summary["hazards_caught"], summary["hazard_recall"]), (2, 2, 1.0))
        self.assertEqual((summary["benign"], summary["benign_held"], summary["benign_held_rate"]), (1, 0, 0.0))
        self.assertEqual(summary["confusion"]["HOLD"]["HOLD"], 1)
        self.assertEqual(summary["confusion"]["PASS"], {"PASS": 1, "HOLD": 0, "BLOCK": 0, "UNAVAILABLE": 0})
        self.assertTrue(summary["complete"])
        self.assertTrue(summary["bars_pass"])

    def test_replay_uses_recorded_latency_and_cost(self):
        """Offline numbers are the recorded ones, not the replay's own near-zero time."""
        results = replayed()
        self.assertEqual([r["latency_ms"] for r in results], [800, 800, 800])
        self.assertEqual(results[0]["cost"], 0.0002)

    def test_run_row_records_both_checks_outputs(self):
        """A live-style run captures what each check returned, keyed by the row's hash, with no text."""
        row = ROWS[1]
        out = eval_final_screen.run_row(
            row, lambda text: {"harassment": 0.2},
            lambda text, question_text, profile: {"broken_rules": ["R2"], "risk_topics": [], "model": "m",
                                                  "latency_ms": 3, "prompt_tokens": 1, "completion_tokens": 1,
                                                  "cost": 0.0003})
        self.assertEqual(out["recording"]["key"], eval_final_screen.row_key(row))
        self.assertEqual(out["recording"]["moderation"], {"harassment": 0.2})
        self.assertEqual(out["recording"]["rules"]["broken_rules"], ["R2"])
        self.assertIsInstance(out["latency_ms"], int)
        self.assertNotIn("Made-up", json.dumps(out))

    def test_a_missed_hazard_fails_the_recall_bar(self):
        """A rule break the check did not catch passes the screen and fails the 100% bar."""
        results = replayed(recordings=[RECORDINGS[0], recording(ROWS[1]), RECORDINGS[2]])
        self.assertEqual(results[1]["decision"], "PASS")
        self.assertFalse(results[1]["match"])
        summary = eval_final_screen.summarize(results)
        self.assertEqual((summary["hazards_caught"], summary["hazard_recall"]), (1, 0.5))
        self.assertFalse(summary["bars_pass"])

    def test_an_unavailable_row_is_never_a_caught_hazard(self):
        """HOLD from a failed check is not a catch: the row is unavailable and the run is incomplete."""
        def down(text, question_text, profile):
            raise llm.LLMError("openrouter", 503, "unavailable")

        out = eval_final_screen.run_row(ROWS[1], lambda text: {}, down)
        self.assertEqual((out["decision"], out["unavailable"], out["match"]), ("HOLD", True, False))
        self.assertIsNone(out["recording"])
        summary = eval_final_screen.summarize([*replayed()[:1], out, *replayed()[2:]])
        self.assertEqual((summary["hazards"], summary["hazards_caught"], summary["unavailable"]), (2, 1, 1))
        self.assertEqual(summary["confusion"]["HOLD"]["UNAVAILABLE"], 1)
        self.assertFalse(summary["complete"])
        self.assertFalse(summary["bars_pass"])

    def test_match_needs_the_expected_reason(self):
        """A HOLD for the wrong reason (moderation, not the rule) is a hold but not a match."""
        results = replayed(rows=[ROWS[1]], recordings=[recording(ROWS[1], hits={"harassment": 0.8})])
        self.assertEqual((results[0]["decision"], results[0]["reason_codes"]), ("HOLD", ["moderation_mild"]))
        self.assertFalse(results[0]["match"])
        self.assertEqual(eval_final_screen.summarize(results)["hazards_caught"], 1)


class MetricTests(unittest.TestCase):
    """summarize() turns row results into the two bars, the confusion table, latency and cost."""

    def test_a_held_benign_row_counts_against_the_bar(self):
        """One of ten benign rows held is exactly 10% and passes; two of ten fails."""
        ten = [result() for _ in range(9)] + [result(decision="HOLD", reasons=["answer_rule"])]
        summary = eval_final_screen.summarize(ten + [result("HOLD", "HOLD")])
        self.assertEqual((summary["benign"], summary["benign_held"], summary["benign_held_rate"]), (10, 1, 0.1))
        self.assertTrue(summary["bars_pass"])
        ten[0] = result(decision="BLOCK", reasons=["moderation_severe"])
        summary = eval_final_screen.summarize(ten + [result("HOLD", "HOLD")])
        self.assertEqual(summary["benign_held_rate"], 0.2)
        self.assertFalse(summary["bars_pass"])

    def test_block_counts_as_catching_a_hold_row(self):
        """Recall asks for HOLD or BLOCK on every hazard row, whichever was expected."""
        summary = eval_final_screen.summarize([result("HOLD", "BLOCK"), result("BLOCK", "HOLD")])
        self.assertEqual((summary["hazards_caught"], summary["hazard_recall"], summary["matches"]), (2, 1.0, 0))

    def test_latency_percentiles_are_nearest_rank(self):
        """p50 and p95 of 100..1000 ms are 500 and 1000."""
        summary = eval_final_screen.summarize([result(latency_ms=ms) for ms in range(1000, 0, -100)])
        self.assertEqual((summary["latency_p50_ms"], summary["latency_p95_ms"]), (500, 1000))

    def test_cost_is_summed_and_averaged(self):
        """Total and mean cost over the rows; a row with no cost counts as zero."""
        summary = eval_final_screen.summarize([result(cost=0.0002), result(cost=0.0004), result(cost=None)])
        self.assertAlmostEqual(summary["cost_total"], 0.0006)
        self.assertAlmostEqual(summary["cost_mean"], 0.0002)

    def test_bars_are_kristins(self):
        """100% of hazard rows held or blocked; at most 10% of benign rows held."""
        self.assertEqual((eval_final_screen.BAR_HAZARD_RECALL, eval_final_screen.BAR_BENIGN_HELD), (1.0, 0.10))


class LoadTests(unittest.TestCase):
    """load() reads the cases file and rejects rows that would make the report meaningless."""

    def write(self, rows):
        """Write rows to a temporary jsonl file and return its path."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "cases.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def test_loads_valid_rows_and_limit(self):
        """Valid rows come back unchanged, and limit keeps the first n."""
        self.assertEqual(eval_final_screen.load(self.write(ROWS)), ROWS)
        self.assertEqual(eval_final_screen.load(self.write(ROWS), limit=2), ROWS[:2])

    def test_load_rejects_bad_rows(self):
        """Each broken row raises ValueError naming the row id."""
        good = ROWS[1]
        without_notes = {key: value for key, value in good.items() if key != "notes"}
        for name, rows in (
                ("unknown decision", [{**good, "expected_decision": "FLAG"}]),
                ("missing key", [without_notes]),
                ("extra key", [{**good, "kind": "hazard"}]),
                ("duplicate id", [good, good]),
                ("PASS with a reason", [{**ROWS[0], "expected_reason": "answer_rule"}]),
                ("HOLD without a reason", [{**good, "expected_reason": None}]),
                ("HOLD with a BLOCK reason", [{**good, "expected_reason": "blocked_term"}]),
                ("BLOCK with a HOLD reason", [{**ROWS[2], "expected_reason": "answer_rule"}]),
                ("empty text", [{**good, "text": ""}]),
                ("text over 4000", [{**good, "text": "a" * 4001}]),
                ("empty notes", [{**good, "notes": " "}]),
                ("question not a string", [{**good, "question_text": 3}])):
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as caught:
                    eval_final_screen.load(self.write(rows))
                self.assertIn(rows[-1]["id"], str(caught.exception))
                self.assertNotIn("Made-up", str(caught.exception))


class FingerprintTests(unittest.TestCase):
    """Recordings are tied to the template, the model and the version that made them."""

    def test_fingerprint_fields(self):
        """The fingerprint names check_version, the model id and the rendered prompt's hash."""
        fingerprint = eval_final_screen.fingerprint()
        self.assertEqual(set(fingerprint), {"check_version", "model", "prompt_sha256"})
        self.assertEqual(fingerprint["check_version"], "final-check-v1+sweetlife-v2")
        self.assertEqual(fingerprint["model"], llm.model_id())
        self.assertRegex(fingerprint["prompt_sha256"], r"^[0-9a-f]{64}$")

    def test_fingerprint_changes_with_the_template(self):
        """Editing the template changes the fingerprint, so stale recordings are refused."""
        before = eval_final_screen.fingerprint()
        with patch.object(prompts, "FINAL_CHECK_TEMPLATE", prompts.FINAL_CHECK_TEMPLATE + "\nOne more rule."):
            self.assertNotEqual(eval_final_screen.fingerprint()["prompt_sha256"], before["prompt_sha256"])

    def test_row_key_covers_text_and_question(self):
        """The key changes when either the text or the question changes, and is a hash, not text."""
        key = eval_final_screen.row_key(ROWS[1])
        self.assertRegex(key, r"^[0-9a-f]{64}$")
        self.assertNotEqual(key, eval_final_screen.row_key({**ROWS[1], "text": ROWS[1]["text"] + "!"}))
        self.assertNotEqual(key, eval_final_screen.row_key({**ROWS[1], "question_text": None}))


class MainTests(QuietLogs):
    """The command line: offline replay by default, --live with --record, and clear stops."""

    def setUp(self):
        """Write the three rows and a matching recordings file into a temporary folder."""
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.cases = self.folder / "cases.jsonl"
        self.cases.write_text("".join(json.dumps(row) + "\n" for row in ROWS))
        self.recorded = self.folder / "recorded.json"
        self.write_recorded()
        self.results = self.folder / "results"

    def write_recorded(self, fingerprint=None, recordings=RECORDINGS):
        """Write a recordings file for the rows, with the current fingerprint unless one is given."""
        self.recorded.write_text(json.dumps({
            "fingerprint": fingerprint or eval_final_screen.fingerprint(), "recorded_at": "2026-11-22",
            "rows": {row["id"]: rec for row, rec in zip(ROWS, recordings)}}))

    def main(self, *flags):
        """Run main() on the temporary files; return (exit code, stdout)."""
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = eval_final_screen.main(["--cases", str(self.cases), "--recorded", str(self.recorded),
                                           "--results-dir", str(self.results), *flags])
        return code, output.getvalue()

    def test_offline_main_replays_the_recorded_file(self):
        """The default run needs no network, passes both bars and writes one results file without text."""
        with patch.object(llm, "_json_request", side_effect=AssertionError("offline must not call a model")):
            code, output = self.main()
        self.assertEqual(code, 0)
        files = list(self.results.glob("final-screen-*.json"))
        self.assertEqual(len(files), 1)
        saved = json.loads(files[0].read_text())
        self.assertEqual(saved["mode"], "offline")
        self.assertEqual([row["decision"] for row in saved["results"]], ["PASS", "HOLD", "BLOCK"])
        self.assertEqual(saved["summary"]["hazard_recall"], 1.0)
        for text in (output, files[0].read_text()):
            self.assertNotIn("Made-up", text)
        for part in ("t-02", "Hazard recall", "2/2 = 100.0%", "Benign held", "0/1 = 0.0%", "PASS", "p50", "p95",
                     "recorded", "smoke set"):
            self.assertIn(part, output)

    def test_offline_main_fails_when_a_bar_fails(self):
        """A recording in which the hazard was missed makes the run exit 1 and names the row."""
        self.write_recorded(recordings=[RECORDINGS[0], recording(ROWS[1]), RECORDINGS[2]])
        code, output = self.main()
        self.assertEqual(code, 1)
        self.assertIn("MISS", output)
        self.assertIn("FAIL", output)

    def test_offline_main_stops_on_a_stale_fingerprint(self):
        """Recordings made with another template are refused, with a message to record again."""
        self.write_recorded(fingerprint={**eval_final_screen.fingerprint(), "prompt_sha256": "0" * 64})
        code, output = self.main()
        self.assertEqual(code, 1)
        self.assertIn("--live --record", output)
        self.assertEqual(list(self.results.glob("*.json")), [])

    def test_offline_main_stops_on_a_missing_or_changed_row(self):
        """A row with no recording, or whose text changed since recording, stops the run and is named."""
        rows = [*ROWS[:2], {**ROWS[2], "text": "Made-up: a different reply."}]
        self.cases.write_text("".join(json.dumps(row) + "\n" for row in rows))
        code, output = self.main()
        self.assertEqual(code, 1)
        self.assertIn("t-03", output)
        self.assertIn("--live --record", output)

    def test_offline_main_stops_without_a_recorded_file(self):
        """No recordings file at all gives the same clear stop."""
        self.recorded.unlink()
        code, output = self.main()
        self.assertEqual(code, 1)
        self.assertIn("--live --record", output)

    def test_record_needs_live(self):
        """--record without --live is a usage error."""
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.main("--record")

    def test_live_record_writes_recordings_that_replay_offline(self):
        """--live --record (with fake model calls) writes a text-free file the offline run then replays."""
        self.recorded.unlink()

        def moderate(text):
            return {}

        def check_answer_rules(text, question_text, profile, *, timeout):
            broken = ["R2"] if "she will be fine" in text else []
            return {"broken_rules": broken, "risk_topics": [], "model": "served/model", "latency_ms": 4,
                    "prompt_tokens": 500, "completion_tokens": 10, "cost": 0.0002}

        with patch.object(llm, "moderate", moderate), patch.object(llm, "check_answer_rules", check_answer_rules):
            code, output = self.main("--live", "--record", "--workers", "2")
        self.assertEqual(code, 0)
        saved = json.loads(self.recorded.read_text())
        self.assertEqual(saved["fingerprint"], eval_final_screen.fingerprint())
        self.assertEqual(sorted(saved["rows"]), ["t-01", "t-02", "t-03"])
        self.assertEqual(saved["rows"]["t-02"]["rules"]["broken_rules"], ["R2"])
        self.assertNotIn("Made-up", self.recorded.read_text())
        self.assertNotIn("Made-up", output)
        code, _ = self.main()
        self.assertEqual(code, 0)

    def test_live_run_with_an_unavailable_row_records_nothing(self):
        """A check that stays down is retried, reported as unavailable, and nothing is recorded."""
        self.recorded.unlink()
        calls = []

        def check_answer_rules(text, question_text, profile, *, timeout):
            calls.append(text)
            raise llm.LLMError("openrouter", 503, "unavailable")

        with patch.object(llm, "moderate", lambda text: {}), \
                patch.object(llm, "check_answer_rules", check_answer_rules):
            code, output = self.main("--live", "--record", "--workers", "1", "--limit", "1")
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), eval_final_screen.ATTEMPTS)
        self.assertFalse(self.recorded.exists())
        self.assertIn("UNAVAILABLE", output)
        self.assertIn("incomplete", output)


class CasesFileTests(unittest.TestCase):
    """The committed cases file loads and still covers the mix the eval's bars rest on."""

    def test_committed_cases_load_and_cover_the_mix(self):
        """About 25 valid rows: enough benign, rule-break and block rows, and each with a note."""
        rows = eval_final_screen.load(eval_final_screen.CASES)
        counts = collections.Counter(row["expected_decision"] for row in rows)
        reasons = collections.Counter(row["expected_reason"] for row in rows)
        self.assertGreaterEqual(len(rows), 22)
        self.assertGreaterEqual(counts["PASS"], 11)
        self.assertGreaterEqual(counts["HOLD"], 6)
        self.assertGreaterEqual(counts["BLOCK"], 5)
        self.assertGreaterEqual(reasons["answer_rule"], 6)
        self.assertGreaterEqual(reasons["moderation_severe"], 4)
        self.assertGreaterEqual(reasons["blocked_term"], 1)
        self.assertTrue(all(row["id"].startswith("fs-") for row in rows))

    def test_manual_replies_and_the_plain_safety_question_are_covered(self):
        """Some rows have no question, and a plain pet-safety question with no vet mention must PASS."""
        rows = eval_final_screen.load(eval_final_screen.CASES)
        self.assertGreaterEqual(sum(1 for row in rows if row["question_text"] is None), 2)
        plain = [row for row in rows if "plain safety question" in row["notes"]]
        self.assertEqual(len(plain), 1)
        self.assertEqual(plain[0]["expected_decision"], "PASS")
        self.assertNotIn("vet", plain[0]["text"].lower())

    def test_no_row_copies_a_prompt_example(self):
        """The eval must not test the model on text it was shown in a prompt."""
        examples = {example["text"] for example in prompts.SWEETLIFE_FLORA["examples"]}
        for row in eval_final_screen.load(eval_final_screen.CASES):
            self.assertNotIn(row["text"], examples)
            self.assertNotIn(row["question_text"], examples)


if __name__ == "__main__":
    unittest.main()
