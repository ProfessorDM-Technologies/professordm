"""Unit tests for the draft prompt (prompts.py) and draft.py.

No test calls a real model or database. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompts import (DRAFT_TEMPLATE, DRAFT_VERSION, SWEETLIFE_FLORA, answer_char_target, draft_prompt,  # noqa: E402
                     prompt_version)


class PromptTests(unittest.TestCase):
    """The draft template stays generic and draft_prompt fills it from the profile and channel."""

    def test_template_is_domain_free(self):
        """The draft template passes the same domain-word check as the triage template in test_triage."""
        for word in ("plant", "leaf", "leaves", "water", "soil", "kristin", "sweetlife"):
            self.assertNotIn(word, DRAFT_TEMPLATE.lower())
        self.assertIn("houseplant care", draft_prompt(SWEETLIFE_FLORA, "instagram"))

    def test_every_placeholder_is_filled(self):
        """No {placeholder} survives rendering, and the doubled braces become one literal JSON example."""
        rendered = draft_prompt(SWEETLIFE_FLORA, "knowledge_app")
        self.assertEqual(re.findall(r"\{[a-z_]+\}", rendered), [])
        self.assertIn('{"ref": "K2", "supports": "a few words on what it supports"}', rendered)

    def test_rules_voice_and_risk_topics(self):
        """Rules render as indented "  - " lines, the voice inline and risk topics joined with "; "."""
        rendered = draft_prompt(SWEETLIFE_FLORA, "instagram")
        rules = "\n".join(f"  - {rule}" for rule in SWEETLIFE_FLORA["answer_rules"])
        self.assertIn(f"- Creator rules:\n{rules}\n- Risk topics: ", rendered)
        self.assertIn(f"- Voice: {SWEETLIFE_FLORA['answer_voice']}\n", rendered)
        self.assertIn("- Risk topics: " + "; ".join(SWEETLIFE_FLORA["risk_topics"]) + ".", rendered)
        self.assertEqual(len(SWEETLIFE_FLORA["answer_rules"]), 4)

    def test_length_target_per_channel(self):
        """The target is 90% of the byte limit in characters, and that number // 6 in words."""
        self.assertIn("under 900 characters, about 150 words", draft_prompt(SWEETLIFE_FLORA, "instagram"))
        self.assertIn("under 3600 characters, about 600 words", draft_prompt(SWEETLIFE_FLORA, "knowledge_app"))
        self.assertEqual(answer_char_target(SWEETLIFE_FLORA, "instagram"), 900)

    def test_unknown_channel_raises(self):
        """A channel without a byte limit raises ValueError."""
        with self.assertRaises(ValueError):
            draft_prompt(SWEETLIFE_FLORA, "email")

    def test_prompt_version(self):
        """Drafts store draft-v1+sweetlife-v2."""
        self.assertEqual(prompt_version(SWEETLIFE_FLORA, DRAFT_VERSION), "draft-v1+sweetlife-v2")


if __name__ == "__main__":
    unittest.main()
