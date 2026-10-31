"""Unit tests for the draft prompt (prompts.py) and draft.py.

No test calls a real model or database. Draft tests patch draft.llm with
FakeLLM, which returns queued replies (or raises queued errors) and checks
the deadline the way llm.write_draft does; search is FakeSearch, and
draft._clock is a FakeClock. Every fixture uses made-up text. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import draft  # noqa: E402  (needs the sys.path line above)
import knowledge  # noqa: E402
import llm  # noqa: E402
from prompts import (DRAFT_TEMPLATE, DRAFT_VERSION, SWEETLIFE_FLORA, answer_char_target, draft_prompt,  # noqa: E402
                     prompt_version)


QUESTION = "My made-up fern has pale new fronds. It sits by a north window and I water it weekly."
ANSWER = ("Pale new growth is often a light clue. Check how many hours of bright light it gets.\n"
          "- Move it closer to the window.\n1. Feel the top of the mix before you water again.")
GENERIC_NOTE = ("Note: This question was flagged for a possible risk topic; check the risk topics and include the "
                "caution if one applies.")
META = {"model": "test-model", "latency_ms": 5, "prompt_tokens": 100, "completion_tokens": 40, "cost": 0.002,
        "attempt": "primary"}


def result(n, similarity=0.62, *, doc="doc-1", hpa="HPA-TEST-0001", score=0.03):
    """Build one knowledge.search result with made-up text."""
    return {"entry_id": f"entry-{n}", "doc_id": doc, "hpa_id": hpa, "source": "doc",
            "title": f"Test Guide > Section {n}", "content": f"Made-up passage {n} about light.",
            "similarity": similarity, "score": score}


def reply(answer=ANSWER, *, sources=(("K1", "light clues"),), coverage="high", missing=(), risks=()):
    """Build one parsed write_draft reply; sources are (ref, supports) pairs."""
    return {"answer": answer, "used_sources": [{"ref": ref, "supports": supports} for ref, supports in sources],
            "knowledge_coverage": coverage, "missing_info": list(missing), "risk_topics": list(risks)}


class FakeClock:
    """Stand-in for draft._clock: a number of seconds that only moves when a test (or FakeLLM) moves it."""

    def __init__(self, now=1000.0):
        """Start at a fixed time."""
        self.now = now

    def __call__(self):
        """Return the current fake time."""
        return self.now


class FakeLLM:
    """Stand-in for the llm module: returns queued draft replies and moderation hits, records every call."""
    # draft.py reads these names from the llm module, so the fake exposes the real ones.
    InvalidOutput = llm.InvalidOutput
    LLMError = llm.LLMError
    MIN_SECONDS_FOR_CALL = llm.MIN_SECONDS_FOR_CALL

    def __init__(self, *replies, flagged=None, clock=None, call_seconds=0):
        """Queue replies (dicts or exceptions) and moderation hits (or an error); each call moves clock by call_seconds."""
        self.replies = list(replies)
        self.flagged = flagged if isinstance(flagged, Exception) else dict(flagged or {})
        self.clock = clock
        self.call_seconds = call_seconds
        self.calls = []

    def write_draft(self, system, user, schema, *, deadline=None):
        """Record the call, refuse to start like llm.write_draft when too little time is left, else reply."""
        self.calls.append({"name": "write_draft", "system": system, "user": user, "schema": schema,
                           "deadline": deadline})
        if deadline is not None and deadline - draft._clock() < self.MIN_SECONDS_FOR_CALL:
            raise llm.LLMError("openrouter", None, "deadline")
        if self.clock:
            self.clock.now += self.call_seconds
        outcome = self.replies.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome, dict(META)

    def moderate(self, text):
        """Record the call and return the configured hits (category -> score), or raise them."""
        self.calls.append({"name": "moderate", "text": text})
        if isinstance(self.flagged, Exception):
            raise self.flagged
        return self.flagged

    def names(self):
        """Return the names of the calls made so far, in order."""
        return [call["name"] for call in self.calls]

    def users(self):
        """Return the user message of every write_draft call."""
        return [call["user"] for call in self.calls if call["name"] == "write_draft"]


class FakeSearch:
    """Stand-in for knowledge.search: records each call and returns fixed results (or raises)."""

    def __init__(self, results=None):
        """Store the results; the default is two passages from two guides, both above the gate."""
        self.results = results if results is not None else [result(1), result(2, 0.5, doc="doc-2",
                                                                             hpa="HPA-TEST-0002")]
        self.calls = []

    def __call__(self, query, creator_id, **kwargs):
        """Record the query, creator and options, then return (or raise) the results."""
        self.calls.append((query, creator_id, kwargs))
        if isinstance(self.results, Exception):
            raise self.results
        return list(self.results)


def run(fake, question=QUESTION, *, search=None, clock=None, **kwargs):
    """Call draft.draft with the fake llm, a FakeSearch and a FakeClock patched in; return the decision."""
    kwargs.setdefault("creator_id", "creator-a")
    with patch.object(draft, "llm", fake), patch.object(draft, "_clock", clock or FakeClock()):
        return draft.draft(question, search=search or FakeSearch(), **kwargs)


def decision(**fields):
    """Build the expected decision: no_draft defaults with the given fields replaced."""
    return {"status": "no_draft", "reason": None, "draft": None, "knowledge_coverage": "none", "missing_info": [],
            "safety_flags": [], "model": None, "prompt_version": "draft-v1+sweetlife-v2", "retrieved": [], **fields}


RETRIEVED = [{"entry_id": "entry-1", "title": "Test Guide > Section 1", "similarity": 0.62},
             {"entry_id": "entry-2", "title": "Test Guide > Section 2", "similarity": 0.5}]


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


class EmptyAndGateTests(unittest.TestCase):
    """Blank questions and weak retrieval end before any model call."""

    def test_empty_question_makes_no_calls(self):
        """A blank or missing question is no_draft / empty_question with no search and no model call."""
        for question in (None, "", "  \n "):
            with self.subTest(question=question):
                fake, search = FakeLLM(), FakeSearch()
                self.assertEqual(run(fake, question, search=search), decision(reason="empty_question"))
                self.assertEqual((fake.calls, search.calls), ([], []))

    def test_gate_below_cutoff_makes_no_model_call(self):
        """A best similarity under DRAFT_MIN_SIMILARITY is no_coverage, keeps what was checked, and calls no model."""
        fake = FakeLLM()
        got = run(fake, search=FakeSearch([result(1, 0.29), result(2, 0.1)]))
        self.assertEqual(got, decision(reason="no_coverage", retrieved=[
            {"entry_id": "entry-1", "title": "Test Guide > Section 1", "similarity": 0.29},
            {"entry_id": "entry-2", "title": "Test Guide > Section 2", "similarity": 0.1}]))
        self.assertEqual(fake.calls, [])
        self.assertEqual(draft.DRAFT_MIN_SIMILARITY, 0.30)

    def test_gate_with_no_results(self):
        """No results count as best similarity 0: no_coverage with nothing retrieved."""
        fake = FakeLLM()
        self.assertEqual(run(fake, search=FakeSearch([])), decision(reason="no_coverage"))
        self.assertEqual(fake.calls, [])

    def test_gate_uses_similarity_never_score(self):
        """A high RRF score cannot lift a low similarity over the gate, and a zero score never blocks the cutoff."""
        fake = FakeLLM()
        self.assertEqual(run(fake, search=FakeSearch([result(1, 0.2, score=0.99)]))["reason"], "no_coverage")
        self.assertEqual(fake.calls, [])
        drafted = run(FakeLLM(reply()), search=FakeSearch([result(1, 0.30, score=0.0)]))
        self.assertEqual(drafted["status"], "drafted")

    def test_search_query_creator_and_settings(self):
        """The query is the question plus every non-empty reply, and search asks for 8 guide chunks only."""
        search = FakeSearch()
        rounds = [{"round": 2, "prompt": "Q2?", "reply": "  "}, {"round": 1, "prompt": "Q1?", "reply": " a north window "},
                  {"round": 3, "prompt": "Q3?", "reply": "about two weeks"}]
        run(FakeLLM(reply()), search=search, rounds=rounds)
        self.assertEqual(search.calls, [(f"{QUESTION}\na north window\nabout two weeks", "creator-a",
                                         {"k": 8, "sources": ["doc"]})])

    def test_search_query_cut_to_2000_characters(self):
        """A long question and replies are cut to the first 2,000 characters."""
        search = FakeSearch()
        run(FakeLLM(reply()), "x" * 1990, search=search, rounds=[{"round": 1, "prompt": "Q?", "reply": "y" * 50}])
        self.assertEqual(search.calls[0][0], "x" * 1990 + "\n" + "y" * 9)

    def test_default_search_is_knowledge_search_at_call_time(self):
        """With search=None, a patched knowledge.search is the one called."""
        search = FakeSearch()
        with patch.object(draft, "llm", FakeLLM(reply())), patch.object(knowledge, "search", search):
            draft.draft(QUESTION, creator_id="creator-a")
        self.assertEqual(len(search.calls), 1)


class DraftedTests(unittest.TestCase):
    """A valid answer becomes a draft with citations, flags and the full decision shape."""

    def test_happy_path_full_decision(self):
        """A valid reply is drafted with citations mapped to entry ids and the full decision shape."""
        fake = FakeLLM(reply(sources=(("K1", " light clues "), ("K2", "check the mix")), coverage="partial",
                             missing=["fertilizer timing"]))
        self.assertEqual(run(fake), decision(
            status="drafted", draft={"ai_text": ANSWER, "used_web_search": False, "citations": [
                {"kind": "knowledge", "ref": "entry-1", "title": "Test Guide > Section 1", "hpa_id": "HPA-TEST-0001",
                 "supports": "light clues"},
                {"kind": "knowledge", "ref": "entry-2", "title": "Test Guide > Section 2", "hpa_id": "HPA-TEST-0002",
                 "supports": "check the mix"}]},
            knowledge_coverage="partial", missing_info=["fertilizer timing"], model="test-model",
            retrieved=RETRIEVED))
        self.assertEqual(fake.names(), ["write_draft", "moderate"])
        self.assertEqual(fake.calls[1]["text"], ANSWER)

    def test_answer_is_stripped(self):
        """Surrounding whitespace is removed from the stored answer and the moderated text."""
        fake = FakeLLM(reply(f"\n  {ANSWER}  \n"))
        self.assertEqual(run(fake)["draft"]["ai_text"], ANSWER)
        self.assertEqual(fake.calls[1]["text"], ANSWER)

    def test_user_message_layout(self):
        """Question, original, sorted rounds (empty reply as ""), note and passages are rendered JSON-quoted."""
        fake = FakeLLM(reply())
        rounds = [{"round": 2, "prompt": "How long?", "reply": None},
                  {"round": 1, "prompt": "Which window?", "reply": ' north "big" one '}]
        run(fake, original_text="pale fronds help", rounds=rounds, safety_flagged=True)
        self.assertEqual(fake.users()[0], "\n".join([
            "Final question:", f'"{QUESTION}"',
            "Original message:", '"pale fronds help"',
            "Clarification:",
            'Round 1 question: "Which window?"', 'Round 1 reply: "north \\"big\\" one"',
            'Round 2 question: "How long?"', 'Round 2 reply: ""',
            GENERIC_NOTE,
            "Passages:",
            '[K1] "Test Guide > Section 1"', '"Made-up passage 1 about light."',
            '[K2] "Test Guide > Section 2"', '"Made-up passage 2 about light."']))

    def test_original_message_left_out_when_equal_or_empty(self):
        """The Original message block appears only when the original differs from the question after strip."""
        for original in (f"  {QUESTION} ", None, "", "   "):
            with self.subTest(original=original):
                fake = FakeLLM(reply())
                run(fake, original_text=original)
                self.assertNotIn("Original message:", fake.users()[0])
                self.assertTrue(fake.users()[0].startswith(f'Final question:\n"{QUESTION}"\nPassages:\n'))

    def test_system_prompt_schema_and_no_deadline(self):
        """The call gets the channel's prompt, a schema whose enums are the refs sent and the profile's topics."""
        fake = FakeLLM(reply())
        run(fake, channel="knowledge_app")
        call = fake.calls[0]
        self.assertEqual(call["system"], draft_prompt(SWEETLIFE_FLORA, "knowledge_app"))
        properties = call["schema"]["properties"]
        self.assertEqual(properties["used_sources"]["items"]["properties"]["ref"]["enum"], ["K1", "K2"])
        self.assertEqual(properties["risk_topics"]["items"]["enum"], SWEETLIFE_FLORA["risk_topics"])
        self.assertEqual(properties["knowledge_coverage"]["enum"], ["high", "partial", "none"])
        self.assertEqual(call["schema"]["required"],
                         ["answer", "used_sources", "knowledge_coverage", "missing_info", "risk_topics"])
        self.assertFalse(call["schema"]["additionalProperties"])
        self.assertIsNone(call["deadline"])

    def test_citations_deduplicated_in_order_of_first_use(self):
        """A ref listed twice gives one citation, kept at its first position with its first supports text."""
        fake = FakeLLM(reply(sources=(("K2", "first"), ("K1", "other"), ("K2", "second"))))
        citations = run(fake)["draft"]["citations"]
        self.assertEqual([(c["ref"], c["supports"]) for c in citations], [("entry-2", "first"), ("entry-1", "other")])

    def test_risk_topics_add_policy_flags_after_moderation_flags(self):
        """Each returned risk topic adds one policy flag after checkpoint 2's moderation flags; nothing blocks."""
        fake = FakeLLM(reply(risks=["pesticides or chemical use", "pesticides or chemical use", "ingesting plants"]),
                       flagged={"violence": 0.6})
        got = run(fake)
        self.assertEqual(got["status"], "drafted")
        self.assertEqual(got["safety_flags"], [
            {"layer": "moderation", "category": "violence", "detail": None},
            {"layer": "policy", "category": "risk_topic", "detail": "pesticides or chemical use"},
            {"layer": "policy", "category": "risk_topic", "detail": "ingesting plants"}])

    def test_missing_info_clip(self):
        """missing_info is stripped, emptied, deduplicated ignoring case, kept to 5 and cut at a word boundary."""
        long_phrase = "how often to feed during the darker months " * 3
        fake = FakeLLM(reply(missing=["  light  levels ", "", "   ", "Light levels", long_phrase, "x" * 90,
                                      "humidity", "pot size", "the sixth one"]))
        self.assertEqual(run(fake)["missing_info"], [
            "light levels", "how often to feed during the darker months how often to feed during the darker",
            "x" * 80, "humidity", "pot size"])

    def test_cut_keeps_whole_words(self):
        """A phrase is cut at the last space within 80 characters, or hard-cut with no space."""
        self.assertEqual(draft._cut("word " * 20), ("word " * 16).strip())
        self.assertEqual(draft._cut("a" * 79 + " b"), "a" * 79)
        self.assertEqual(draft._cut("a" * 80 + " b"), "a" * 80)


CHECK_CASES = [
    ("bad_fields", {**reply(), "answer": 5}),
    ("bad_fields", {key: value for key, value in reply().items() if key != "risk_topics"}),
    ("bad_fields", reply(coverage="mostly")),
    ("bad_fields", {**reply(), "used_sources": [{"ref": "K1"}]}),
    ("bad_fields", {**reply(), "missing_info": "one topic"}),
    ("empty_answer", reply("  \n ")),
    ("too_long", reply("a" * 1001)),
    ("markdown", reply("# A heading\nThen text.")),
    ("markdown", reply("Text first.\n   ## An indented heading")),
    ("markdown", reply("Keep it **bright** for now.")),
    ("markdown", reply("Use the `mix` check.")),
    ("url", reply("Read more at https://example.com today.")),
    ("url", reply("Read more at WWW.example.com today.")),
    ("ref_marker", reply("Bright light helps [K1].")),
    ("citation_marker", reply("Bright light helps [1].")),
    ("citation_marker", reply("Bright light helps [2-3].")),
    ("internal_id", reply("See HPA-FUND-0001 for more.")),
    ("internal_id", reply("See TROUBLE-0004 for more.")),
    ("banned_word", reply("As an AI I would check the light.")),
    ("banned_word", reply("The passages say to check the light.")),
    ("banned_word", reply("One passage says to check the light.")),
    ("banned_word", reply("My Knowledge Base says to check the light.")),
    ("unknown_ref", reply(sources=(("K1", "light"), ("K9", "made up")))),
    ("no_sources", reply(sources=())),
    ("bad_risk_topic", reply(risks=["made-up topic"])),
]


class ValidationTests(unittest.TestCase):
    """Each check rejects with its own code; one retry names the reason and can fix it."""

    def test_each_check_rejects_then_the_retry_fixes_it(self):
        """Every failure code triggers one retry whose last line is that code's fixed reason, then drafts."""
        for code, bad in CHECK_CASES:
            with self.subTest(code=code, answer=bad.get("answer")):
                fake = FakeLLM(bad, reply())
                got = run(fake)
                self.assertEqual(got["status"], "drafted")
                first, second = fake.users()
                reason = draft.RETRY_REASONS[code].format(char_target=900)
                self.assertEqual(second, f"{first}\nYour previous reply was rejected: {reason}. Return a corrected reply.")

    def test_not_json_from_write_draft_is_retried(self):
        """InvalidOutput("not_json") from write_draft counts as one failure with the schema reason."""
        fake = FakeLLM(llm.InvalidOutput("not_json"), reply())
        self.assertEqual(run(fake)["status"], "drafted")
        self.assertTrue(fake.users()[1].endswith(
            "rejected: the reply was not valid JSON matching the schema. Return a corrected reply."))

    def test_not_a_dict_is_not_json(self):
        """A reply that is not a JSON object fails with not_json."""
        self.assertEqual(draft._check(["answer"], ["K1"], SWEETLIFE_FLORA, "instagram"), "not_json")

    def test_allowed_formatting(self):
        """The word source, "- " bullets, "1." steps and words containing "ai" all pass in one call."""
        answer = ("The source is usually light, said simply.\n- Check the window.\n1. Wait a week.\n  2. Look again.\n"
                  "Avoid harsh sun - it can scorch. Aim for 6 to 8 hours, 20-25 C.")
        fake = FakeLLM(reply(answer))
        self.assertEqual(run(fake)["status"], "drafted")
        self.assertEqual(fake.names(), ["write_draft", "moderate"])

    def test_first_failure_wins(self):
        """With several problems, the earliest check in the order decides the reason."""
        fake = FakeLLM(reply("# Heading with https://example.com [K1]", sources=(("K9", "x"),)), reply())
        run(fake)
        self.assertIn("it used markdown", fake.users()[1])

    def test_invalid_twice_returns_invalid_output(self):
        """Two invalid replies give no_draft / invalid_output with coverage none, the model and the passages sent."""
        fake = FakeLLM(reply("**one**"), reply("[K1] two"))
        self.assertEqual(run(fake), decision(reason="invalid_output", model="test-model", retrieved=RETRIEVED))
        self.assertEqual(fake.names(), ["write_draft", "write_draft"])

    def test_retry_line_carries_no_question_or_answer_text(self):
        """The retry adds only the fixed reason line: no question text and none of the rejected answer."""
        rejected = "Unique rejected wording about **mist**."
        fake = FakeLLM(reply(rejected), reply())
        run(fake)
        first, second = fake.users()
        added = second[len(first):]
        self.assertEqual(added, "\nYour previous reply was rejected: it used markdown; use plain text with no "
                                "headings, asterisks or backticks. Return a corrected reply.")
        self.assertNotIn("Unique rejected wording", second)
        self.assertNotIn(QUESTION, added)

    def test_too_long_reason_names_the_channel_target(self):
        """The too_long reason states the channel's character target."""
        fake = FakeLLM(reply("a" * 4001), reply())
        run(fake, channel="knowledge_app")
        self.assertIn("too long, keep it under 3600 characters", fake.users()[1])

    def test_channel_byte_limits(self):
        """1000 bytes is the Instagram limit and 4000 the app limit, both inclusive."""
        for channel, size, status in (("instagram", 1000, "drafted"), ("knowledge_app", 1001, "drafted"),
                                      ("knowledge_app", 4000, "drafted"), ("knowledge_app", 4001, "no_draft")):
            with self.subTest(channel=channel, size=size):
                fake = FakeLLM(reply("a" * size), reply("a" * size))
                self.assertEqual(run(fake, channel=channel)["status"], status)

    def test_multibyte_text_is_measured_in_bytes(self):
        """600 two-byte letters are 1200 bytes, over Instagram's 1000 although only 600 characters."""
        fake = FakeLLM(reply("é" * 600), reply("é" * 500))
        got = run(fake)
        self.assertIn("too long", fake.users()[1])
        self.assertEqual((got["status"], len(got["draft"]["ai_text"].encode("utf-8"))), ("drafted", 1000))
        self.assertEqual(run(FakeLLM(reply("🌿" * 251), reply("🌿" * 251)))["reason"], "invalid_output")

    def test_coverage_none_with_empty_answer_is_no_coverage_on_the_first_call(self):
        """Coverage none skips the answer checks: no retry, no moderation, the model's missing_info kept."""
        fake = FakeLLM(reply("", sources=(), coverage="none", missing=["  a made-up topic "]))
        self.assertEqual(run(fake), decision(reason="no_coverage", missing_info=["a made-up topic"], model="test-model",
                                             retrieved=RETRIEVED))
        self.assertEqual(fake.names(), ["write_draft"])

    def test_coverage_none_still_checks_fields_first(self):
        """Bad fields are rejected even when coverage says none, since coverage is only trusted on valid fields."""
        fake = FakeLLM({**reply(coverage="none"), "answer": None}, reply())
        self.assertEqual(run(fake)["status"], "drafted")
        self.assertIn("not valid JSON matching the schema", fake.users()[1])

    def test_coverage_none_ignores_bad_answer_content(self):
        """With valid fields and coverage none, markdown or unknown refs in the unused answer cause no retry."""
        fake = FakeLLM(reply("# junk [K9]", sources=(("K9", "x"),), coverage="none", risks=["made-up topic"]))
        self.assertEqual(run(fake)["reason"], "no_coverage")
        self.assertEqual(fake.names(), ["write_draft"])


class SafetyTests(unittest.TestCase):
    """Checkpoint 2 drops a severe or blocked answer but keeps its flags."""

    def test_severe_moderation_blocks_and_drops_the_text(self):
        """A severe moderation hit is no_draft / safety_blocked with no text, all flags and the model's coverage."""
        fake = FakeLLM(reply(risks=["ingesting plants"], missing=["dose"], coverage="partial"),
                       flagged={"harassment/threatening": 0.9})
        self.assertEqual(run(fake), decision(
            reason="safety_blocked", knowledge_coverage="partial", missing_info=["dose"], model="test-model",
            retrieved=RETRIEVED, safety_flags=[
                {"layer": "moderation", "category": "harassment/threatening", "detail": None},
                {"layer": "policy", "category": "risk_topic", "detail": "ingesting plants"}]))

    def test_blocked_term_blocks(self):
        """A blocked term in the answer is safety_blocked with a rules flag."""
        got = run(FakeLLM(reply("Honestly kys, then check the light.")))
        self.assertEqual((got["status"], got["reason"], got["draft"]), ("no_draft", "safety_blocked", None))
        self.assertEqual(got["safety_flags"], [{"layer": "rules", "category": "blocked_term", "detail": None}])

    def test_mild_moderation_only_flags(self):
        """A non-severe hit at the flag threshold is kept as a flag and the draft goes through."""
        got = run(FakeLLM(reply(), flagged={"violence": 0.5, "harassment": 0.2}))
        self.assertEqual(got["status"], "drafted")
        self.assertEqual(got["safety_flags"], [{"layer": "moderation", "category": "violence", "detail": None}])


class NoteTests(unittest.TestCase):
    """The risk note is generic or names the checkpoint-1 topics, and only listed topics get through."""

    def note(self, **kwargs):
        """Return the Note line sent to the model, or None when there is none."""
        fake = FakeLLM(reply())
        run(fake, **kwargs)
        return next((line for line in fake.users()[0].splitlines() if line.startswith("Note: ")), None)

    def test_generic_note_without_topics(self):
        """A flagged question without topics gets the generic line."""
        self.assertEqual(self.note(safety_flagged=True), GENERIC_NOTE)

    def test_named_topics_with_unknown_values_dropped(self):
        """Listed topics are named once each, in order; anything else (such as DM text) is dropped."""
        topics = ["pesticides or chemical use", "made-up DM text", "pesticides or chemical use", "ingesting plants"]
        self.assertEqual(self.note(safety_flagged=True, flagged_topics=topics),
                         "Note: This question was flagged for these risk topics: pesticides or chemical use; "
                         "ingesting plants. Include the caution.")

    def test_only_unknown_topics_fall_back_to_generic(self):
        """When every topic is unknown, the generic line is used and none of them reaches the prompt."""
        fake = FakeLLM(reply())
        run(fake, safety_flagged=True, flagged_topics=["made-up DM text"])
        self.assertIn(GENERIC_NOTE, fake.users()[0])
        self.assertNotIn("made-up DM text", fake.users()[0])

    def test_no_note_when_not_flagged(self):
        """Without safety_flagged there is no note, even if topics are passed."""
        self.assertIsNone(self.note(flagged_topics=["ingesting plants"]))


class DeadlineTests(unittest.TestCase):
    """time_left becomes a deadline; no call starts with less than MIN_SECONDS_FOR_CALL left."""

    def test_deadline_is_clock_plus_time_left(self):
        """The deadline passed to write_draft is _clock() at the start plus time_left."""
        fake = FakeLLM(reply())
        run(fake, clock=FakeClock(500.0), time_left=100)
        self.assertEqual(fake.calls[0]["deadline"], 600.0)

    def test_too_short_before_the_first_call_raises(self):
        """With under 45 s left, the first call does not start and LLMError propagates so the job retries."""
        fake = FakeLLM(reply())
        with self.assertRaises(llm.LLMError) as caught:
            run(fake, time_left=30)
        self.assertEqual(caught.exception.code, "deadline")
        self.assertEqual(fake.replies, [reply()])

    def test_too_short_before_the_retry_returns_invalid_output(self):
        """When the first call leaves under 45 s, the retry is skipped: invalid_output with one call only."""
        clock = FakeClock()
        fake = FakeLLM(reply("**bold**"), reply(), clock=clock, call_seconds=20)
        got = run(fake, clock=clock, time_left=60)
        self.assertEqual(got, decision(reason="invalid_output", model="test-model", retrieved=RETRIEVED))
        self.assertEqual(fake.names(), ["write_draft"])

    def test_enough_time_for_the_retry(self):
        """With 45 s or more left after the first call, the retry runs with the same deadline."""
        clock = FakeClock()
        fake = FakeLLM(reply("**bold**"), reply(), clock=clock, call_seconds=20)
        self.assertEqual(run(fake, clock=clock, time_left=65)["status"], "drafted")
        self.assertEqual([call["deadline"] for call in fake.calls if call["name"] == "write_draft"], [1065.0, 1065.0])


class ErrorTests(unittest.TestCase):
    """Outages and configuration errors propagate; a bad channel fails before any call."""

    def test_llm_errors_propagate(self):
        """LLMError from search, write_draft or moderation is raised, never turned into a decision."""
        cases = [(FakeLLM(), FakeSearch(llm.LLMError("supabase", 500, "XX000"))),
                 (FakeLLM(llm.LLMError("openrouter", 503, None)), None),
                 (FakeLLM(reply(), flagged=llm.LLMError("openai", 500, None)), None)]
        for fake, search in cases:
            with self.subTest(fake=fake.replies, search=search):
                with self.assertRaises(llm.LLMError):
                    run(fake, search=search)

    def test_llm_error_on_the_retry_propagates(self):
        """An outage during the retry is raised too."""
        with self.assertRaises(llm.LLMError):
            run(FakeLLM(reply("**bold**"), llm.LLMError("openrouter", None, "TimeoutError")))

    def test_runtime_error_propagates(self):
        """A missing key surfaces as RuntimeError."""
        with self.assertRaises(RuntimeError):
            run(FakeLLM(RuntimeError("Missing OPENROUTER_API_KEY")))

    def test_unknown_channel_raises_before_any_call(self):
        """A channel without a byte limit raises ValueError before search or any model call."""
        fake, search = FakeLLM(reply()), FakeSearch()
        with self.assertRaises(ValueError):
            run(fake, search=search, channel="email")
        self.assertEqual((fake.calls, search.calls), ([], []))


class LogTests(unittest.TestCase):
    """One log line with counts, codes, tokens and cost, never text."""

    def test_log_line_has_metadata_but_no_text(self):
        """No question, answer, passage, title or missing_info text reaches the log."""
        fake = FakeLLM(reply("**first**"), reply(missing=["made-up gap"], risks=["ingesting plants"]))
        with self.assertLogs("draft", level="INFO") as logs:
            run(fake, rounds=[{"round": 1, "prompt": "Which window?", "reply": "north facing"}])
        output = "\n".join(logs.output)
        for expected in ("status=drafted", "reason=none", "coverage=high", "passages=2", "best_similarity=0.620",
                         "flags=1", "attempts=2", "attempt=primary", "invalid=markdown", "prompt_tokens=200",
                         "completion_tokens=80", "cost=0.004000"):
            self.assertIn(expected, output)
        for text in (QUESTION, ANSWER, "first", "Made-up passage", "Test Guide", "made-up gap", "north facing",
                     "ingesting plants"):
            self.assertNotIn(text, output)

    def test_log_line_without_a_call(self):
        """An empty question logs zero attempts and no similarity."""
        with self.assertLogs("draft", level="INFO") as logs:
            run(FakeLLM(), "")
        self.assertIn("reason=empty_question coverage=none passages=0 best_similarity=none flags=0 attempts=0 "
                      "attempt=none", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
