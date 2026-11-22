"""Unit tests for final_screen.py (the final answer screen, checkpoint 3).

No test calls a real model: screen_final() takes the moderation call and the
answer-rules check as arguments, and every test passes fakes that return
fixed results (or raise, or block) and record what they saw. Every fixture
uses made-up text. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import hashlib
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


if __name__ == "__main__":
    unittest.main()
