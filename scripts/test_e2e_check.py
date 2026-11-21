import unittest

from e2e_check import check_question, embedding_dims, leak_phrases

VECTOR = "[" + ",".join(["0.1"] * 1536) + "]"


def good():
    q = {"id": "q1", "status": "delivered", "question_text": "How much light does a ZZ plant need?"}
    d = {
        "origin": {"id": "m1", "status": "ready_for_question", "category": "expert_question"},
        "others": ["How often should I fertilize my monstera?"],
        "draft": {"ai_text": "AI answer text.", "final_text": "My edited answer.", "approved_at": "2026-11-21T22:34:00Z"},
        "outbound": [{"status": "sent"}],
        "entries": [{"source": "question", "content": "My edited answer.", "tags": ["zz plant"], "published": False,
                     "embedding": VECTOR}],
        "logs": {"draft_done": True, "delivery_pass": True, "publish_pass": True, "stored": True},
        "leaks": 0,
    }
    return q, d


def failed(q, d):
    return [name for name, ok, _ in check_question(q, d) if not ok]


class CheckQuestionTests(unittest.TestCase):
    def test_clean_question_passes_every_step(self):
        self.assertEqual(failed(*good()), [])

    def test_earlier_question_repeated_fails_step_3(self):
        # DEF-01: an answered question joined into the next one.
        q, d = good()
        q["question_text"] = d["others"][0] + "\n" + q["question_text"]
        self.assertEqual(failed(q, d), ["3 question has only its own DMs"])

    def test_unedited_draft_fails_step_5(self):
        q, d = good()
        d["draft"]["final_text"] = d["draft"]["ai_text"]
        d["entries"][0]["content"] = d["draft"]["ai_text"]
        self.assertEqual(failed(q, d), ["5 creator edited + approved"])

    def test_saved_ai_draft_instead_of_final_text_fails_step_7(self):
        q, d = good()
        d["entries"][0]["content"] = d["draft"]["ai_text"]
        self.assertEqual(failed(q, d), ["7 Q&A saved"])

    def test_duplicate_or_missing_entry_fails_step_7(self):
        for entries in ([], [good()[1]["entries"][0]] * 2):
            q, d = good()
            d["entries"] = entries
            self.assertEqual(failed(q, d), ["7 Q&A saved"])

    def test_wrong_embedding_size_fails_step_7(self):
        q, d = good()
        d["entries"][0]["embedding"] = "[0.1,0.2]"
        self.assertEqual(failed(q, d), ["7 Q&A saved"])

    def test_not_delivered_fails_step_6(self):
        q, d = good()
        d["outbound"] = [{"status": "failed"}]
        self.assertEqual(failed(q, d), ["6 delivered to Instagram"])

    def test_text_in_logs_fails_step_8(self):
        q, d = good()
        d["leaks"] = 2
        self.assertEqual(failed(q, d), ["8 no DM or answer text in logs"])

    def test_detail_never_contains_dm_or_answer_text(self):
        q, d = good()
        details = " ".join(detail for _, _, detail in check_question(q, d))
        for text in (q["question_text"], d["draft"]["final_text"], d["draft"]["ai_text"]):
            self.assertNotIn(text, details)


class HelperTests(unittest.TestCase):
    def test_leak_phrases_are_letters_and_spaces_only(self):
        phrases = leak_phrases('It\'s "4 feet" from a north-facing window, so medium light.', "ok", None)
        self.assertEqual(len(phrases), 1)
        self.assertRegex(phrases[0], r"^[A-Za-z ]+$")

    def test_embedding_dims(self):
        self.assertEqual(embedding_dims(VECTOR), 1536)
        self.assertEqual(embedding_dims([0.1, 0.2]), 2)
        self.assertEqual(embedding_dims(None), 0)


if __name__ == "__main__":
    unittest.main()
