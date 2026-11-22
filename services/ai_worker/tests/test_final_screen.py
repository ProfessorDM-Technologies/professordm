"""Unit tests for final_screen.py (the final answer screen, checkpoint 3).

No test calls a real model: screen_final() takes the moderation call and the
answer-rules check as arguments, and every test passes fakes that return
fixed results (or raise, or block) and record what they saw. Every fixture
uses made-up text. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import hashlib
import logging
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import final_screen  # noqa: E402  (needs the sys.path line above)
import llm  # noqa: E402
from prompts import SWEETLIFE_FLORA  # noqa: E402


TEXT = "A made-up reply about moving a fern closer to the window."
QUESTION = "A made-up question about a pale fern?"
TOPIC = "plants toxic to pets or kids"
RULE_2 = {"id": "R2", "text": SWEETLIFE_FLORA["answer_rules"][1]}
BLOCKED_TERM_FLAG = {"layer": "rules", "category": "blocked_term", "detail": None}


class FakeModerate:
    """Stand-in for llm.moderate: returns the configured hits (category -> score) or raises, and records each call."""

    def __init__(self, hits=None, error=None):
        """Store the hits to return, or the error to raise instead."""
        self.hits = dict(hits or {})
        self.error = error
        self.calls = []

    def __call__(self, text):
        """Record the text, then raise the error or return the hits."""
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.hits


class FakeRules:
    """Stand-in for the answer-rules check: returns queued outcomes in order (the last one repeats)."""

    def __init__(self, *outcomes):
        """Queue outcomes; each is a result to return or an exception to raise."""
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, text, question_text, profile):
        """Record the call, then return or raise the next outcome."""
        self.calls.append((text, question_text, profile))
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def rules(broken=(), topics=(), model="served/model"):
    """Build one answer-rules result, shaped like llm.check_answer_rules returns it."""
    return {"broken_rules": broken if isinstance(broken, str) else list(broken),
            "risk_topics": topics if isinstance(topics, str) else list(topics), "model": model,
            "latency_ms": 5, "prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0001}


def run(hits=None, outcome=None, *, moderate=None, check=None, text=TEXT, question=QUESTION,
        profile=SWEETLIFE_FLORA, **kwargs):
    """Run screen_final with fakes; return (result, the moderation fake, the rules fake).

    Pass hits and outcome for the common case, or moderate= / check= to use a
    prepared fake (an error, or several queued outcomes).
    """
    moderate = moderate or FakeModerate(hits)
    check = check or FakeRules(outcome if outcome is not None else rules())
    result = final_screen.screen_final(text, question_text=question, profile=profile,
                                       moderate=moderate, check_rules=check, **kwargs)
    return result, moderate, check


def moderation(*categories):
    """Build the moderation flags expected for the given categories, in order."""
    return [{"layer": "moderation", "category": category, "detail": None} for category in categories]


def capture_logs(test):
    """Collect final_screen's log records for one test, and keep them out of the test output.

    Unlike assertLogs this does not fail when nothing is logged, so it can sit
    in setUp for tests that expect no line at all.
    """
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("final_screen")
    logger.addHandler(handler)
    logger.propagate = False

    def restore():
        logger.removeHandler(handler)
        logger.propagate = True

    test.addCleanup(restore)
    return records


def outcome_of(result):
    """Return the (decision, next_actor) pair of a result."""
    return result["decision"], result["next_actor"]


class DecisionTests(unittest.TestCase):
    """Each kind of finding alone gives the contract's decision, reason code, categories, rules and flags."""

    def test_clean_text_passes(self):
        """Nothing found: PASS with every list empty, and each check saw the exact text once."""
        result, moderate, check = run()
        self.assertEqual(result, {
            "decision": "PASS", "next_actor": "none", "reason_codes": [], "categories": [], "rules": [],
            "flags": [], "text_sha256": hashlib.sha256(TEXT.encode("utf-8")).hexdigest(),
            "check_version": "final-check-v1+sweetlife-v2", "model": "served/model"})
        self.assertEqual(moderate.calls, [TEXT])
        self.assertEqual(check.calls, [(TEXT, QUESTION, SWEETLIFE_FLORA)])

    def test_severe_hit_blocks(self):
        """A severe moderation category blocks with no override."""
        result, _, _ = run({"harassment/threatening": 0.9})
        self.assertEqual(outcome_of(result), ("BLOCK", "creator"))
        self.assertEqual(result["reason_codes"], ["moderation_severe"])
        self.assertEqual(result["categories"], ["harassment/threatening"])
        self.assertEqual(result["flags"], moderation("harassment/threatening"))
        self.assertEqual(result["rules"], [])

    def test_base_blocked_term_blocks(self):
        """A base blocked phrase blocks, with the rules-layer flag from the contract's flags table."""
        result, _, _ = run(text="ok kys then")
        self.assertEqual(outcome_of(result), ("BLOCK", "creator"))
        self.assertEqual(result["reason_codes"], ["blocked_term"])
        self.assertEqual(result["categories"], ["blocked_term"])
        self.assertEqual(result["flags"], [BLOCKED_TERM_FLAG])

    def test_profile_blocked_term_blocks(self):
        """A creator's own blocked term blocks the same way; without it in the profile the text passes."""
        profile = {**SWEETLIFE_FLORA, "extra_blocked_terms": ["leaf thief"]}
        result, _, _ = run(text="the leaf  thief struck", profile=profile)
        self.assertEqual(outcome_of(result), ("BLOCK", "creator"))
        self.assertEqual(result["reason_codes"], ["blocked_term"])
        self.assertEqual(outcome_of(run(text="the leaf  thief struck")[0]), ("PASS", "none"))

    def test_mild_hit_holds_for_the_creator(self):
        """A non-severe moderation hit at 0.5 or more holds; the creator may confirm and send."""
        result, _, _ = run({"harassment": 0.7})
        self.assertEqual(outcome_of(result), ("HOLD", "creator"))
        self.assertEqual(result["reason_codes"], ["moderation_mild"])
        self.assertEqual(result["categories"], ["harassment"])
        self.assertEqual(result["flags"], moderation("harassment"))

    def test_mild_hit_below_threshold_passes(self):
        """Pest-killing wording scores under 0.5 for violence and must not hold the reply."""
        result, _, _ = run({"violence": 0.45})
        self.assertEqual(outcome_of(result), ("PASS", "none"))
        self.assertEqual((result["reason_codes"], result["categories"], result["flags"]), ([], [], []))

    def test_broken_rule_holds_with_id_text_and_flag(self):
        """A broken answer rule holds, names the rule by id and text, and flags it with the id as detail."""
        result, _, _ = run(outcome=rules(broken=["R2"]))
        self.assertEqual(outcome_of(result), ("HOLD", "creator"))
        self.assertEqual(result["reason_codes"], ["answer_rule"])
        self.assertEqual(result["categories"], [])
        self.assertEqual(result["rules"], [RULE_2])
        self.assertEqual(result["flags"], [{"layer": "policy", "category": "answer_rule", "detail": "R2"}])

    def test_risk_topic_alone_passes_with_a_flag(self):
        """A risk topic is information only: PASS, no reason code, one policy flag."""
        result, _, _ = run(outcome=rules(topics=[TOPIC]))
        self.assertEqual(outcome_of(result), ("PASS", "none"))
        self.assertEqual((result["reason_codes"], result["rules"]), ([], []))
        self.assertEqual(result["flags"], [{"layer": "policy", "category": "risk_topic", "detail": TOPIC}])


class CombiningTests(unittest.TestCase):
    """Every finding from every check is listed, in a fixed order, whatever the decision (contract v2.1)."""

    def test_severe_plus_broken_rule_blocks_with_both_findings(self):
        """BLOCK wins, and the mild hit, the broken rules and the risk topic are all still listed."""
        result, _, _ = run({"harassment": 0.7, "harassment/threatening": 0.6},
                           rules(broken=["R4", "R1"], topics=[TOPIC]))
        self.assertEqual(outcome_of(result), ("BLOCK", "creator"))
        self.assertEqual(result["reason_codes"], ["moderation_severe", "moderation_mild", "answer_rule"])
        self.assertEqual(result["categories"], ["harassment", "harassment/threatening"])
        self.assertEqual([rule["id"] for rule in result["rules"]], ["R1", "R4"])
        self.assertEqual(result["rules"][1]["text"], SWEETLIFE_FLORA["answer_rules"][3])
        self.assertEqual(result["flags"], [
            *moderation("harassment", "harassment/threatening"),
            {"layer": "policy", "category": "answer_rule", "detail": "R1"},
            {"layer": "policy", "category": "answer_rule", "detail": "R4"},
            {"layer": "policy", "category": "risk_topic", "detail": TOPIC}])

    def test_mild_plus_broken_rule_holds_with_both(self):
        """Two mild findings still hold for the creator and list both reasons."""
        result, _, _ = run({"harassment": 0.7}, rules(broken=["R2"]))
        self.assertEqual(outcome_of(result), ("HOLD", "creator"))
        self.assertEqual(result["reason_codes"], ["moderation_mild", "answer_rule"])

    def test_blocked_term_plus_mild_and_rule(self):
        """A blocked term blocks, and blocked_term is listed after the moderation categories."""
        result, _, _ = run({"harassment": 0.7}, rules(broken=["R2"]), text="ok kys then")
        self.assertEqual(outcome_of(result), ("BLOCK", "creator"))
        self.assertEqual(result["reason_codes"], ["blocked_term", "moderation_mild", "answer_rule"])
        self.assertEqual(result["categories"], ["harassment", "blocked_term"])
        self.assertEqual(result["flags"], [*moderation("harassment"), BLOCKED_TERM_FLAG,
                                           {"layer": "policy", "category": "answer_rule", "detail": "R2"}])

    def test_duplicates_from_the_check_give_no_duplicate_flags(self):
        """A rule or topic the check lists twice appears once."""
        result, _, _ = run(outcome=rules(broken=["R2", "R2"], topics=[TOPIC, TOPIC]))
        self.assertEqual(result["rules"], [RULE_2])
        self.assertEqual(result["flags"], [{"layer": "policy", "category": "answer_rule", "detail": "R2"},
                                           {"layer": "policy", "category": "risk_topic", "detail": TOPIC}])

    def test_risk_topic_flags_follow_profile_order(self):
        """Topics come out in the profile's order, whatever order the check used."""
        topics = SWEETLIFE_FLORA["risk_topics"]
        result, _, _ = run(outcome=rules(topics=list(reversed(topics))))
        self.assertEqual([flag["detail"] for flag in result["flags"]], topics)


class HashAndVersionTests(unittest.TestCase):
    """The hash covers the exact text, and check_version names the template and the profile."""

    def test_hash_is_of_the_exact_text(self):
        """Leading and trailing whitespace is hashed and screened as given, never stripped."""
        text = "  leading and trailing spaces \n"
        result, moderate, check = run(text=text)
        self.assertEqual(result["text_sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertNotEqual(result["text_sha256"], hashlib.sha256(text.strip().encode("utf-8")).hexdigest())
        self.assertEqual(moderate.calls, [text])
        self.assertEqual(check.calls[0][0], text)

    def test_non_ascii_text_hashes_as_utf8(self):
        """Accented letters and emoji are hashed as their UTF-8 bytes."""
        text = "Über 🌿"
        self.assertEqual(run(text=text)[0]["text_sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())

    def test_check_version_uses_the_profile_version(self):
        """check_version is FINAL_CHECK_VERSION plus the profile's own version."""
        result, _, _ = run(profile={**SWEETLIFE_FLORA, "version": "other-v9"})
        self.assertEqual(result["check_version"], "final-check-v1+other-v9")

    def test_no_question_is_passed_as_none(self):
        """A manual reply has no question; the rules check is told so."""
        _, _, check = run(question=None)
        self.assertIsNone(check.calls[0][1])

    def test_no_latency_key(self):
        """screen_final leaves latency_ms to the handler."""
        self.assertNotIn("latency_ms", run()[0])


UNAVAILABLE = ("HOLD", "system")


def outage():
    """Build a moderation or model outage, as llm raises it."""
    return llm.LLMError("openai", 503, "unavailable")


class FailureTests(unittest.TestCase):
    """A check that fails never counts as clean: the screen fails closed (SAF05) and never raises."""

    def setUp(self):
        """Capture the screen's own warning and error lines, so the test output stays clean."""
        self.records = capture_logs(self)

    def test_moderation_failure_holds_for_the_system(self):
        """Moderation down: HOLD for the system; the rules check still ran and its model is reported."""
        result, _, _ = run(moderate=FakeModerate(error=outage()))
        self.assertEqual(outcome_of(result), UNAVAILABLE)
        self.assertEqual(result["reason_codes"], ["check_unavailable"])
        self.assertEqual((result["categories"], result["rules"], result["flags"]), ([], [], []))
        self.assertEqual(result["model"], "served/model")

    def test_rules_failure_holds_for_the_system(self):
        """The rules check down: HOLD for the system, and model is null."""
        result, _, _ = run(check=FakeRules(llm.LLMError("openrouter", None, "TimeoutError")))
        self.assertEqual(outcome_of(result), UNAVAILABLE)
        self.assertEqual(result["reason_codes"], ["check_unavailable"])
        self.assertIsNone(result["model"])

    def test_rules_invalid_twice_holds_for_the_system(self):
        """Invalid output is retried once; a second invalid reply is a failed check."""
        result, _, check = run(check=FakeRules(llm.InvalidOutput("bad_rule")))
        self.assertEqual(len(check.calls), 2)
        self.assertEqual(outcome_of(result), UNAVAILABLE)
        self.assertEqual(result["reason_codes"], ["check_unavailable"])

    def test_rules_invalid_once_then_valid_is_used(self):
        """The retry's valid result is used like any other."""
        result, _, check = run(check=FakeRules(llm.InvalidOutput("not_json"), rules(broken=["R2"])))
        self.assertEqual(len(check.calls), 2)
        self.assertEqual(outcome_of(result), ("HOLD", "creator"))
        self.assertEqual(result["reason_codes"], ["answer_rule"])

    def test_rules_outage_is_not_retried(self):
        """Only invalid output earns a retry; an outage would just add latency."""
        _, _, check = run(check=FakeRules(outage(), rules()))
        self.assertEqual(len(check.calls), 1)

    def test_rules_failed_but_severe_hit_blocks(self):
        """A severe hit blocks even though the other check failed; both are listed."""
        result, _, _ = run({"sexual/minors": 0.9}, check=FakeRules(outage()))
        self.assertEqual(outcome_of(result), ("BLOCK", "creator"))
        self.assertEqual(result["reason_codes"], ["moderation_severe", "check_unavailable"])
        self.assertEqual(result["flags"], moderation("sexual/minors"))

    def test_moderation_failed_but_broken_rule_stays_unavailable(self):
        """A creator must not confirm past a check that did not run, so HOLD/system beats HOLD/creator."""
        result, _, _ = run(moderate=FakeModerate(error=outage()), outcome=rules(broken=["R2"]))
        self.assertEqual(outcome_of(result), UNAVAILABLE)
        self.assertEqual(result["reason_codes"], ["answer_rule", "check_unavailable"])
        self.assertEqual(result["rules"], [RULE_2])

    def test_mild_hit_with_rules_failure_stays_unavailable(self):
        """A mild hit plus a failed rules check is still HOLD for the system, with both listed."""
        result, _, _ = run({"harassment": 0.7}, check=FakeRules(outage()))
        self.assertEqual(outcome_of(result), UNAVAILABLE)
        self.assertEqual(result["reason_codes"], ["moderation_mild", "check_unavailable"])
        self.assertEqual(result["categories"], ["harassment"])

    def test_blocked_term_blocks_when_moderation_is_down(self):
        """The term check is local, so a blocked term still blocks without moderation (contract v2.1)."""
        result, _, _ = run(moderate=FakeModerate(error=outage()), text="ok kys then")
        self.assertEqual(outcome_of(result), ("BLOCK", "creator"))
        self.assertEqual(result["reason_codes"], ["blocked_term", "check_unavailable"])
        self.assertEqual(result["categories"], ["blocked_term"])
        self.assertEqual(result["flags"], [BLOCKED_TERM_FLAG])

    def test_missing_key_is_unavailable_and_logs_a_config_error(self):
        """A missing key is a configuration problem: check_unavailable plus an error line naming no value."""
        result, _, _ = run(moderate=FakeModerate(error=RuntimeError("Missing OPENAI_API_KEY")))
        self.assertEqual(outcome_of(result), UNAVAILABLE)
        self.assertEqual(result["reason_codes"], ["check_unavailable"])
        errors = [record.getMessage() for record in self.records if record.levelname == "ERROR"]
        self.assertEqual(errors, ["Final screen config_error stage=screen"])

    def test_both_checks_failing_lists_unavailable_once(self):
        """Two failed checks still give one check_unavailable, with nothing else in the response."""
        result, _, _ = run(moderate=FakeModerate(error=outage()), check=FakeRules(outage()))
        self.assertEqual(outcome_of(result), UNAVAILABLE)
        self.assertEqual(result["reason_codes"], ["check_unavailable"])
        self.assertEqual((result["categories"], result["rules"], result["flags"]), ([], [], []))
        self.assertIsNone(result["model"])

    def test_unexpected_exception_fails_closed(self):
        """A bug inside a check is treated like an outage, never as a clean result."""
        for fakes in ({"check": FakeRules(TypeError("boom"))}, {"moderate": FakeModerate(error=KeyError("boom"))}):
            with self.subTest(fakes=list(fakes)):
                result, _, _ = run(**fakes)
                self.assertEqual(outcome_of(result), UNAVAILABLE)

    def test_out_of_vocabulary_results_are_unavailable(self):
        """Anything but known rule ids and the profile's topics is a failed check, and none of it is returned."""
        for bad in (rules(broken=["the reply says it is fine"]), rules(topics=["made-up topic"]),
                    rules(broken="R2"), rules(topics=TOPIC), rules(broken=[2]), None, "R2",
                    {"risk_topics": []}, {"broken_rules": []}):
            with self.subTest(bad=bad):
                result, _, check = run(check=FakeRules(bad))
                self.assertEqual(outcome_of(result), UNAVAILABLE)
                self.assertEqual(result["reason_codes"], ["check_unavailable"])
                self.assertEqual((result["rules"], result["flags"]), ([], []))
                self.assertIsNone(result["model"])
                self.assertEqual(len(check.calls), 1)  # a wrong-shaped result is not retried

    def test_failure_logs_name_the_stage_and_type_but_no_text(self):
        """Each failed check logs one line with its stage and error type, never the text or the question."""
        run(moderate=FakeModerate(error=outage()), check=FakeRules(llm.InvalidOutput("not_json")))
        lines = sorted(record.getMessage() for record in self.records)
        self.assertEqual(lines, ["Final screen stage=rules FAIL error_type=invalid_output",
                                 "Final screen stage=screen FAIL error_type=llm_error"])
        self.assertNotIn(TEXT, "\n".join(lines))
        self.assertNotIn(QUESTION, "\n".join(lines))


class ParallelTests(unittest.TestCase):
    """Layers 1 and 3 run at the same time, so the screen costs one slow call, not two."""

    def test_both_checks_run_at_the_same_time(self):
        """Each fake waits for the other to have started; run one after the other, the first would time out."""
        barrier = threading.Barrier(2, timeout=2)

        def moderate(text):
            barrier.wait()
            return {}

        def check(text, question_text, profile):
            barrier.wait()
            return rules()

        result = final_screen.screen_final(TEXT, profile=SWEETLIFE_FLORA, moderate=moderate, check_rules=check)
        self.assertEqual(outcome_of(result), ("PASS", "none"))


class DeadlineTests(unittest.TestCase):
    """The screen answers by its own deadline, whatever the model calls are still doing."""

    def setUp(self):
        """Capture the screen's warning lines, and prepare an event that releases any blocked fake."""
        self.records = capture_logs(self)
        # Every blocking fake waits on this, and cleanup always sets it, so no
        # thread outlives the test run.
        self.release = threading.Event()
        self.addCleanup(self.release.set)
        self.finished = threading.Event()

    def blocked_rules(self, outcome):
        """Build a rules check that hangs until released, then returns the outcome."""
        def check(text, question_text, profile):
            self.release.wait(5)
            self.finished.set()
            return outcome
        return check

    def blocked_moderate(self, text):
        """A moderation call that hangs until released."""
        self.release.wait(5)
        return {}

    def test_a_check_that_never_returns_is_unavailable_within_the_deadline(self):
        """The rules check hangs: the screen answers at its deadline with check_unavailable."""
        started = time.monotonic()
        result = final_screen.screen_final(TEXT, profile=SWEETLIFE_FLORA, moderate=FakeModerate(),
                                           check_rules=self.blocked_rules(rules()), deadline_seconds=0.2)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(outcome_of(result), UNAVAILABLE)
        self.assertEqual(result["reason_codes"], ["check_unavailable"])
        self.assertIsNone(result["model"])
        self.assertIn("Final screen stage=rules FAIL error_type=deadline",
                      [record.getMessage() for record in self.records])

    def test_moderation_that_never_returns_is_unavailable(self):
        """Moderation hangs: the same answer, and the finished rules check still reports its model."""
        started = time.monotonic()
        result = final_screen.screen_final(TEXT, profile=SWEETLIFE_FLORA, moderate=self.blocked_moderate,
                                           check_rules=FakeRules(rules()), deadline_seconds=0.2)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(outcome_of(result), UNAVAILABLE)
        self.assertEqual(result["model"], "served/model")

    def test_severe_hit_that_finished_first_still_blocks(self):
        """A severe hit that arrived in time blocks, even though the other check never finished."""
        result = final_screen.screen_final(TEXT, profile=SWEETLIFE_FLORA,
                                           moderate=FakeModerate({"self-harm/intent": 0.4}),
                                           check_rules=self.blocked_rules(rules()), deadline_seconds=0.2)
        self.assertEqual(outcome_of(result), ("BLOCK", "creator"))
        self.assertEqual(result["reason_codes"], ["moderation_severe", "check_unavailable"])

    def test_a_result_that_arrives_after_the_deadline_is_thrown_away(self):
        """A check that finishes late never changes the response that was already returned."""
        result = final_screen.screen_final(TEXT, profile=SWEETLIFE_FLORA, moderate=FakeModerate(),
                                           check_rules=self.blocked_rules(rules(broken=["R2"])),
                                           deadline_seconds=0.2)
        before = dict(result)
        self.release.set()
        self.assertTrue(self.finished.wait(2))
        time.sleep(0.05)  # give a wrongly attached callback the chance to run
        self.assertEqual(result, before)
        self.assertEqual(outcome_of(result), UNAVAILABLE)
        self.assertEqual((result["rules"], result["flags"], result["model"]), ([], [], None))
        self.assertNotIn("answer_rule", result["reason_codes"])

    def test_no_rules_retry_with_under_three_seconds_left(self):
        """With a 2 second deadline there is never room for a retry: one call, then unavailable."""
        result, _, check = run(check=FakeRules(llm.InvalidOutput("not_json"), rules()), deadline_seconds=2)
        self.assertEqual(len(check.calls), 1)
        self.assertEqual(outcome_of(result), UNAVAILABLE)

    def test_rules_retry_when_time_remains(self):
        """With exactly RULES_RETRY_MIN_SECONDS left on the clock the retry still happens."""
        clock = SteppedClock(100.0)
        check = FakeRules(llm.InvalidOutput("not_json"), rules())
        result, _, _ = run(check=clock.jump_after(check, to=108.0), clock=clock)
        self.assertEqual(len(check.calls), 2)
        self.assertEqual(outcome_of(result), ("PASS", "none"))

    def test_retry_uses_the_injected_clock(self):
        """The retry rule reads the screen's own clock: 2 seconds left after the first call means no retry."""
        clock = SteppedClock(100.0)
        check = FakeRules(llm.InvalidOutput("not_json"), rules())
        result, _, _ = run(check=clock.jump_after(check, to=109.0), clock=clock)
        self.assertEqual(len(check.calls), 1)
        self.assertEqual(outcome_of(result), UNAVAILABLE)

    def test_constants(self):
        """The contract's 11 second deadline and the 3 second retry floor."""
        self.assertEqual((final_screen.SCREEN_DEADLINE_SECONDS, final_screen.RULES_RETRY_MIN_SECONDS), (11, 3))


class SteppedClock:
    """A fake clock that stays at one reading until a wrapped call has run, then jumps to another.

    Driven by what happened, not by how many times the clock was read, so the
    tests do not depend on the implementation's number of clock reads.
    """

    def __init__(self, now):
        """Start at a fixed time."""
        self.now = now

    def __call__(self):
        """Return the current fake time."""
        return self.now

    def jump_after(self, check, *, to):
        """Wrap a rules fake so the clock reads `to` once its first call has returned or raised."""
        def wrapped(text, question_text, profile):
            try:
                return check(text, question_text, profile)
            finally:
                self.now = to
        return wrapped


if __name__ == "__main__":
    unittest.main()
