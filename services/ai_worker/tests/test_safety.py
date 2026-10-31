"""Unit tests for safety.py.

No test calls a real model: screen() takes the moderation call as an
argument, and every test passes FakeModerate, which returns fixed hits and
records the text it saw. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import safety
import triage
from prompts import SWEETLIFE_FLORA


TEXT = "my fern has pale fronds, it sits by a north window and I water it weekly"


class FakeModerate:
    """Stand-in for llm.moderate: returns the configured hits (category -> score) and records each call."""

    def __init__(self, hits=None):
        """Store the hits to return; an empty dict means nothing was flagged."""
        self.hits = dict(hits or {})
        self.calls = []

    def __call__(self, text):
        """Record the text and return the hits."""
        self.calls.append(text)
        return self.hits


def screen(hits=None, text=TEXT, profile=SWEETLIFE_FLORA):
    """Run safety.screen with a FakeModerate returning hits; return (result, fake)."""
    fake = FakeModerate(hits)
    return safety.screen(text, profile, moderate=fake), fake


def moderation(*categories):
    """Build the moderation flags expected for the given categories, in order."""
    return [{"layer": "moderation", "category": category, "detail": None} for category in categories]


class ScreenTests(unittest.TestCase):
    """screen() reports severe hits, flags, blocked terms and crisis exactly as triage always has."""
    def test_clean_text_has_nothing(self):
        """No moderation hits and no blocked term give an empty result."""
        result, _ = screen()
        self.assertEqual(result, {"severe": [], "flags": [], "blocked_term": False, "crisis": False})

    def test_unscored_severe_blocks_at_any_score(self):
        """self-harm/intent and sexual/minors are severe on OpenAI's flag alone, even at a tiny score."""
        for category in ("self-harm/intent", "sexual/minors"):
            with self.subTest(category=category):
                result, _ = screen({category: 0.01})
                self.assertEqual(result["severe"], [category])
                self.assertEqual(result["flags"], moderation(category))

    def test_scored_severe_blocks_only_at_threshold(self):
        """Threat categories are severe at 0.5 or more; just below, they are neither severe nor flagged."""
        for category in sorted(safety.SCORED_SEVERE):
            with self.subTest(category=category):
                below, _ = screen({category: 0.49})
                self.assertEqual((below["severe"], below["flags"]), ([], []))
                at, _ = screen({category: 0.5})
                self.assertEqual((at["severe"], at["flags"]), ([category], moderation(category)))
                above, _ = screen({category: 0.8})
                self.assertEqual(above["severe"], [category])

    def test_mild_hits_flag_only_at_threshold(self):
        """A non-severe hit flags at 0.5 or more and never makes the text severe."""
        below, _ = screen({"violence": 0.49})
        self.assertEqual(below, {"severe": [], "flags": [], "blocked_term": False, "crisis": False})
        above, _ = screen({"violence": 0.5, "harassment": 0.9})
        self.assertEqual(above["severe"], [])
        self.assertEqual(above["flags"], moderation("violence", "harassment"))

    def test_illicit_violent_is_flagged_but_never_severe(self):
        """illicit/violent (pest-killing language) flags at 0.8 but never blocks."""
        result, _ = screen({"illicit/violent": 0.8})
        self.assertEqual((result["severe"], result["flags"]), ([], moderation("illicit/violent")))
        self.assertNotIn("illicit/violent", safety.SEVERE)

    def test_flags_keep_moderation_order_with_severe_and_mild_together(self):
        """Severe and mild flags come out in moderation's order; low mild hits are left out."""
        result, _ = screen({"harassment": 0.7, "harassment/threatening": 0.6, "self-harm": 0.2,
                            "violence": 0.55})
        self.assertEqual(result["severe"], ["harassment/threatening"])
        self.assertEqual(result["flags"], moderation("harassment", "harassment/threatening", "violence"))

    def test_crisis_only_for_self_harm(self):
        """crisis is True only when a severe hit is self-harm, not for other severe categories or mild self-harm."""
        self.assertTrue(screen({"self-harm/instructions": 0.3})[0]["crisis"])
        self.assertTrue(screen({"self-harm": 0.8, "self-harm/intent": 0.8})[0]["crisis"])
        self.assertFalse(screen({"sexual/minors": 0.9})[0]["crisis"])
        self.assertFalse(screen({"harassment/threatening": 0.9})[0]["crisis"])
        # self-harm on its own is not in SEVERE: a mild flag, no crisis.
        mild, _ = screen({"self-harm": 0.8})
        self.assertEqual((mild["severe"], mild["crisis"], mild["flags"]), ([], False, moderation("self-harm")))

    def test_moderate_is_called_once_with_the_text(self):
        """screen() makes exactly one moderation call, with the text it was given."""
        _, fake = screen({"violence": 0.9}, text="a made-up answer about repotting")
        self.assertEqual(fake.calls, ["a made-up answer about repotting"])


class BlockedTermTests(unittest.TestCase):
    """Blocked terms match whole words with any spacing, plus the profile's own terms."""
    def test_blocked_term_adds_a_rules_flag_after_moderation_flags(self):
        """A match sets blocked_term and appends the rules flag after any moderation flags."""
        result, _ = screen({"harassment": 0.7}, text="just KILL   yourself already")
        self.assertTrue(result["blocked_term"])
        self.assertEqual(result["severe"], [])
        self.assertEqual(result["flags"], [*moderation("harassment"),
                                           {"layer": "rules", "category": "blocked_term", "detail": None}])

    def test_severe_hit_skips_the_blocked_term_check(self):
        """With a severe hit the block is already decided, so no rules flag is added (triage's order)."""
        result, _ = screen({"sexual/minors": 0.9}, text="send nudes")
        self.assertEqual((result["blocked_term"], result["flags"]), (False, moderation("sexual/minors")))

    def test_whole_words_only(self):
        """A term inside a longer word does not match."""
        self.assertTrue(safety.blocked_term("ok kys", SWEETLIFE_FLORA))
        self.assertFalse(safety.blocked_term("the skys are gray over my fern", SWEETLIFE_FLORA))

    def test_profile_terms_are_added(self):
        """extra_blocked_terms from the profile match like base terms, with extra spaces."""
        profile = {**SWEETLIFE_FLORA, "extra_blocked_terms": ["leaf thief", "  "]}
        self.assertTrue(screen(text="the leaf  thief struck", profile=profile)[0]["blocked_term"])
        self.assertFalse(screen(text="a leaf thiefs guide", profile=profile)[0]["blocked_term"])
        self.assertFalse(screen(text="the leaf thief struck")[0]["blocked_term"])

    def test_flag_shape(self):
        """flag() builds the stored shape with detail None by default."""
        self.assertEqual(safety.flag("policy", "risk_topic", "ingesting plants"),
                         {"layer": "policy", "category": "risk_topic", "detail": "ingesting plants"})
        self.assertEqual(safety.flag("rules", "blocked_term"),
                         {"layer": "rules", "category": "blocked_term", "detail": None})


class ReexportTests(unittest.TestCase):
    """triage still exposes the moved names, so older callers keep working."""
    def test_triage_reexports_the_same_objects(self):
        """triage.X is the very object in safety, and the private aliases point at the new functions."""
        for name in ("SEVERE", "SCORED_SEVERE", "MILD_FLAG_THRESHOLD", "SEVERE_FLAG_THRESHOLD", "BLOCKED_TERMS"):
            with self.subTest(name=name):
                self.assertIs(getattr(triage, name), getattr(safety, name))
        self.assertIs(triage._flag, safety.flag)
        self.assertIs(triage._blocked_term, safety.blocked_term)


if __name__ == "__main__":
    unittest.main()
