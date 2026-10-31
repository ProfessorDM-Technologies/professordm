"""Unit tests for triage.py and llm.py.

No test calls a real model. Triage tests patch triage.llm with FakeLLM, which
returns queued results; llm tests patch the HTTP layer. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import json
import os
import re
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm
import triage
from prompts import CATEGORIES, SWEETLIFE_FLORA, TRIAGE_TEMPLATE, triage_prompt


CONTRACTS = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "src" / "index.ts"
DECISION_KEYS = {"status", "category", "service_kind", "confidence", "reason", "prompt_version",
                 "model", "safety_flags", "question", "clarification", "outbound"}
CLARIFY_TEXT = "Which plant is it, and how often do you water it?"
DM = "My calathea has crispy brown tips. It's in a bright bathroom and I water weekly."


def result(category="expert_question", confidence=0.94, *, service_kind=None, risk_reason=None):
    """Build a fake llm.classify result with sensible defaults; a risk_reason implies risk_flag."""
    return {"category": category, "service_kind": service_kind, "confidence": confidence,
            "reason": "Asks about crispy calathea leaf tips", "risk_flag": risk_reason is not None,
            "risk_reason": risk_reason, "model": "test-model", "latency_ms": 5,
            "prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0}


class FakeLLM:
    """Stand-in for the llm module: returns queued results and records every call, with no network."""
    # triage.py reads these names from the llm module, so the fake exposes the real ones.
    InvalidOutput = llm.InvalidOutput
    LLMError = llm.LLMError
    MODERATION_MODEL = "omni-moderation-latest"

    def __init__(self, *results, flagged=None, clarifications=(CLARIFY_TEXT,), moderation_error=None):
        """Queue classify results, moderation hits (category -> score), clarifications and an optional moderation error."""
        self.results = list(results)
        self.flagged = dict(flagged or {})
        self.clarifications = list(clarifications)
        self.moderation_error = moderation_error
        self.calls = []

    def moderate(self, text):
        """Record the call and return the configured moderation hits, or raise the configured error."""
        self.calls.append(("moderate", text))
        if self.moderation_error:
            raise self.moderation_error
        return self.flagged

    def classify(self, text, recent_messages, profile, rounds=None):
        """Record the call and return (or raise) the next queued classify result."""
        self.calls.append(("classify", text, recent_messages, rounds))
        outcome = self.results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def write_clarification(self, text, recent_messages, profile, rounds=None):
        """Record the call and return (or raise) the next queued clarification text."""
        self.calls.append(("clarify", text, recent_messages, rounds))
        outcome = self.clarifications.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def model_id(self):
        """Return a fixed model id for decisions built without a classify result."""
        return "test-model"

    def names(self):
        """Return the names of the calls made so far, in order."""
        return [call[0] for call in self.calls]


def run(fake, text=DM, recent_messages=None, profile=None):
    """Call triage.triage with the fake llm patched in."""
    with patch.object(triage, "llm", fake):
        return triage.triage(text, recent_messages, profile)


def rerun(fake, original, rounds, recent_messages=None):
    """Call triage.reassess with the fake llm patched in."""
    with patch.object(triage, "llm", fake):
        return triage.reassess(original, rounds, recent_messages)


ROUND_1 = {"round": 1, "prompt": CLARIFY_TEXT, "reply": "  a calathea, north window, I water every week  "}
ROUND_2 = {"round": 2, "prompt": "How long has it been happening?", "reply": "about two weeks"}


def contract_values(name):
    """Read one exported string array from packages/contracts/src/index.ts."""
    source = CONTRACTS.read_text()
    block = re.search(rf"export const {name} = \[(.*?)\] as const", source, re.S).group(1)
    return tuple(re.findall(r'"([a-z_]+)"', block))


class ContractTests(unittest.TestCase):
    """The decision values stay in sync with the shared contracts and the template stays generic."""
    def test_categories_and_statuses_mirror_shared_contracts(self):
        """Categories, statuses and outbound types match packages/contracts exactly."""
        self.assertEqual(CATEGORIES, contract_values("MESSAGE_CATEGORIES"))
        statuses = set(contract_values("INBOUND_MESSAGE_STATUS"))
        for status in ("closed_no_action", "blocked", "service_routed", "awaiting_clarification",
                       "ready_for_question", "creator_decision"):
            self.assertIn(status, statuses)
        outbound = set(contract_values("OUTBOUND_TYPES"))
        self.assertTrue({"clarification", "decline"} <= outbound)

    def test_template_is_domain_free(self):
        """The generic triage template never mentions plants or the creator; the domain comes from the profile."""
        for word in ("plant", "leaf", "leaves", "water", "soil", "kristin", "sweetlife"):
            self.assertNotIn(word, TRIAGE_TEMPLATE.lower())
        self.assertIn("houseplant care", triage_prompt(SWEETLIFE_FLORA))


class RoutingTests(unittest.TestCase):
    """Each row of the routing table produces the right status and full decision shape."""
    def test_expert_question_is_ready_for_question(self):
        """A confident expert_question becomes ready_for_question with a question and the full decision shape."""
        fake = FakeLLM(result())
        decision = run(fake)
        self.assertEqual(decision, {
            "status": "ready_for_question", "category": "expert_question", "service_kind": None,
            "confidence": 0.94, "reason": "Asks about crispy calathea leaf tips",
            "prompt_version": "triage-v4+sweetlife-v2", "model": "test-model", "safety_flags": [],
            "question": {"question_text": DM, "safety_flagged": False},
            "clarification": None, "outbound": None})
        self.assertEqual(fake.names(), ["moderate", "classify"])

    def test_needs_clarification_asks_round_one(self):
        """A vague DM gets a round-1 clarification, sent as an outbound, with the clarify version recorded."""
        fake = FakeLLM(result("needs_clarification", 0.9))
        decision = run(fake, "why is it yellow")
        self.assertEqual(decision, {
            "status": "awaiting_clarification", "category": "needs_clarification", "service_kind": None,
            "confidence": 0.9, "reason": "Asks about crispy calathea leaf tips",
            "prompt_version": "triage-v4+clarify-v4+sweetlife-v2", "model": "test-model",
            "safety_flags": [], "question": None,
            "clarification": {"round": 1, "prompt": CLARIFY_TEXT},
            "outbound": {"type": "clarification", "text": CLARIFY_TEXT}})
        self.assertEqual(fake.names(), ["moderate", "classify", "clarify"])

    def test_social_and_spam_close_without_action(self):
        """Social and spam close with no question, clarification, reply or flags."""
        for category in ("social", "spam_irrelevant"):
            with self.subTest(category=category):
                decision = run(FakeLLM(result(category, 0.99)), "Good morning!")
                self.assertEqual((decision["status"], decision["category"]), ("closed_no_action", category))
                self.assertEqual((decision["question"], decision["clarification"], decision["outbound"],
                                  decision["safety_flags"]), (None, None, None, []))

    def test_service_request_is_routed_with_its_kind(self):
        """A service_request is service_routed and keeps its service_kind."""
        decision = run(FakeLLM(result("service_request", 0.97, service_kind="business")),
                       "Do you ship cuttings to Canada?")
        self.assertEqual((decision["status"], decision["category"], decision["service_kind"]),
                         ("service_routed", "service_request", "business"))
        self.assertEqual((decision["question"], decision["outbound"]), (None, None))

    def test_non_severe_safety_concern_goes_to_creator_with_flag(self):
        """A safety_concern label (not blocked) goes to creator_decision with a policy flag and no reply."""
        decision = run(FakeLLM(result("safety_concern", 0.95)), "My dog just ate a leaf and is shaking")
        self.assertEqual((decision["status"], decision["category"]), ("creator_decision", "safety_concern"))
        self.assertEqual(decision["safety_flags"], [{"layer": "policy", "category": "safety_concern", "detail": None}])
        self.assertEqual((decision["question"], decision["outbound"]), (None, None))

    def test_low_confidence_goes_to_creator_and_keeps_category(self):
        """Below CONFIDENCE_CUTOFF every category goes to creator_decision, keeps its label and writes no clarification."""
        for category in CATEGORIES:
            with self.subTest(category=category):
                fake = FakeLLM(result(category, 0.55, service_kind="business" if category == "service_request" else None))
                decision = run(fake)
                self.assertEqual((decision["status"], decision["category"], decision["confidence"]),
                                 ("creator_decision", category, 0.55))
                self.assertEqual((decision["question"], decision["clarification"], decision["outbound"]),
                                 (None, None, None))
                self.assertNotIn("clarify", fake.names())

    def test_cutoff_is_inclusive(self):
        """Confidence exactly at CONFIDENCE_CUTOFF still routes automatically."""
        decision = run(FakeLLM(result(confidence=triage.CONFIDENCE_CUTOFF)))
        self.assertEqual(decision["status"], "ready_for_question")

    def test_recent_messages_join_into_question_text(self):
        """Split DMs join into question_text; blanks are dropped and only the latest DM is moderated."""
        fake = FakeLLM(result())
        decision = run(fake, "it's by an east window, watered every 10 days",
                       ["hey quick question", "  ", "my string of pearls looks shriveled"])
        self.assertEqual(decision["question"]["question_text"],
                         "hey quick question\nmy string of pearls looks shriveled\n"
                         "it's by an east window, watered every 10 days")
        self.assertEqual(fake.calls[1][2], ["hey quick question", "my string of pearls looks shriveled"])
        self.assertEqual(fake.calls[0], ("moderate", "it's by an east window, watered every 10 days"))


class SafetyTests(unittest.TestCase):
    """Safety layers 1 (moderation) and 2 (blocked terms) block, flag or pass as designed."""
    def test_severe_moderation_hit_blocks_without_classify(self):
        """Every SEVERE category blocks without calling classify and sends the right decline text."""
        for category in sorted(triage.SEVERE):
            with self.subTest(category=category):
                score = 0.6 if category in triage.SCORED_SEVERE else 0.05
                fake = FakeLLM(flagged={"harassment": 0.7, category: score})
                decision = run(fake, "a harmful message")
                reply = "crisis_text" if category.startswith("self-harm") else "decline_text"
                self.assertEqual(decision, {
                    "status": "blocked", "category": "safety_concern", "service_kind": None,
                    "confidence": None, "reason": f"Moderation flagged {category}",
                    "prompt_version": "triage-v4+sweetlife-v2", "model": "omni-moderation-latest",
                    "safety_flags": [{"layer": "moderation", "category": "harassment", "detail": None},
                                     {"layer": "moderation", "category": category, "detail": None}],
                    "question": None, "clarification": None,
                    "outbound": {"type": "decline", "text": SWEETLIFE_FLORA[reply]}})
                self.assertEqual(fake.names(), ["moderate"])

    def test_illicit_violent_never_blocks_and_flags_at_mild_threshold(self):
        """illicit/violent never blocks (pest-killing language), even at 0.80, and only flags at the mild threshold."""
        fake = FakeLLM(result(), flagged={"illicit/violent": 0.286, "violence": 0.85})
        decision = run(fake, "these thrips need to DIE 😤 how do i murder them all")
        self.assertEqual(decision["status"], "ready_for_question")
        self.assertEqual(decision["safety_flags"], [{"layer": "moderation", "category": "violence", "detail": None}])
        self.assertEqual(fake.names(), ["moderate", "classify"])
        fake = FakeLLM(result(), flagged={"illicit": 0.849, "illicit/violent": 0.798, "violence": 0.64})
        decision = run(fake, "whats the best way to nuke them?? 💀", ["i want to straight up murder these bugs"])
        self.assertEqual(decision["status"], "ready_for_question")
        self.assertEqual([f["category"] for f in decision["safety_flags"]], ["illicit", "illicit/violent", "violence"])
        self.assertNotIn("illicit/violent", triage.SEVERE)

    def test_harmful_illicit_violent_request_reaches_creator_with_flags(self):
        """A genuinely harmful illicit/violent request still reaches creator_decision with moderation and policy flags."""
        fake = FakeLLM(result("safety_concern", 0.98), flagged={"illicit": 0.858, "illicit/violent": 0.615})
        decision = run(fake, "a request to poison someone")
        self.assertEqual((decision["status"], decision["category"], decision["outbound"]),
                         ("creator_decision", "safety_concern", None))
        self.assertEqual(decision["safety_flags"], [
            {"layer": "moderation", "category": "illicit", "detail": None},
            {"layer": "moderation", "category": "illicit/violent", "detail": None},
            {"layer": "policy", "category": "safety_concern", "detail": None}])
        for category in sorted(triage.SCORED_SEVERE):
            with self.subTest(category=category):
                decision = run(FakeLLM(result(), flagged={category: 0.49}), "a borderline message")
                self.assertEqual((decision["status"], decision["safety_flags"]), ("ready_for_question", []))
        self.assertEqual(triage.SEVERE_FLAG_THRESHOLD, 0.5)

    def test_high_scoring_threat_still_blocks(self):
        """A threat at or above SEVERE_FLAG_THRESHOLD still blocks with the decline text."""
        fake = FakeLLM(flagged={"harassment": 0.739, "harassment/threatening": 0.524, "violence": 0.241})
        decision = run(fake, "Answer me or I'll make you regret it")
        self.assertEqual((decision["status"], decision["reason"]),
                         ("blocked", "Moderation flagged harassment/threatening"))
        self.assertEqual(decision["safety_flags"], [
            {"layer": "moderation", "category": "harassment", "detail": None},
            {"layer": "moderation", "category": "harassment/threatening", "detail": None}])
        self.assertEqual(decision["outbound"]["text"], SWEETLIFE_FLORA["decline_text"])
        self.assertEqual(fake.names(), ["moderate"])

    def test_self_harm_block_sends_crisis_text_not_decline(self):
        """A self-harm block sends crisis_text (with 988), never the generic decline."""
        decision = run(FakeLLM(flagged={"self-harm": 0.78, "self-harm/intent": 0.82}), "a message in crisis")
        self.assertEqual(decision["outbound"], {"type": "decline", "text": SWEETLIFE_FLORA["crisis_text"]})
        self.assertIn("988", decision["outbound"]["text"])
        self.assertNotEqual(SWEETLIFE_FLORA["crisis_text"], SWEETLIFE_FLORA["decline_text"])

    def test_blocked_term_blocks_without_classify(self):
        """A blocked term blocks without classify, ignoring case and extra spaces."""
        fake = FakeLLM()
        decision = run(fake, "just KILL   yourself already")
        self.assertEqual((decision["status"], decision["category"], decision["model"]),
                         ("blocked", "safety_concern", None))
        self.assertEqual(decision["safety_flags"], [{"layer": "rules", "category": "blocked_term", "detail": None}])
        self.assertEqual(decision["outbound"], {"type": "decline", "text": SWEETLIFE_FLORA["decline_text"]})
        self.assertEqual(fake.names(), ["moderate"])

    def test_blocked_terms_match_whole_words_and_profile_terms(self):
        """Blocked terms match whole words only, include the profile's terms, and no longer include doxx."""
        profile = {**SWEETLIFE_FLORA, "extra_blocked_terms": ["leaf thief"]}
        self.assertEqual(run(FakeLLM(), "the leaf  thief struck", profile=profile)["status"], "blocked")
        for text in ("The skys are gray, my fern is drooping, it's by a window and watered weekly",
                     "a leaf thiefs guide", "someone tried to doxx me after I posted my plant shelf, what do I do"):
            with self.subTest(text=text):
                self.assertEqual(run(FakeLLM(result()), text, profile=profile)["status"], "ready_for_question")

    def test_mild_moderation_hit_above_threshold_flags_and_continues(self):
        """A non-severe hit at or above MILD_FLAG_THRESHOLD adds a flag and marks the question, without blocking."""
        fake = FakeLLM(result(), flagged={"violence": 0.85})
        decision = run(fake, "a message moderation scores as violent")
        self.assertEqual(decision["status"], "ready_for_question")
        self.assertEqual(decision["safety_flags"], [{"layer": "moderation", "category": "violence", "detail": None}])
        self.assertTrue(decision["question"]["safety_flagged"])

    def test_pest_killing_phrases_below_threshold_do_not_flag(self):
        """Pest-killing phrases at their real moderation scores add no flag."""
        cases = {"How do I kill the fungus gnats in my pothos soil?": {"violence": 0.401},
                 "how do i kill mealybugs on my hoya": {},
                 "whats the best spray to kill spider mites": {"violence": 0.2},
                 "gonna nuke these aphids with neem lol": {"violence": 0.427}}
        for text, flagged in cases.items():
            with self.subTest(text=text):
                decision = run(FakeLLM(result(), flagged=flagged), text)
                self.assertEqual((decision["status"], decision["safety_flags"]), ("ready_for_question", []))
                self.assertFalse(decision["question"]["safety_flagged"])
        self.assertEqual(triage.MILD_FLAG_THRESHOLD, 0.5)

    def test_risk_flag_adds_policy_flag_and_keeps_status(self):
        """A risk topic adds a policy flag with the topic as detail and keeps ready_for_question."""
        decision = run(FakeLLM(result(risk_reason="plants toxic to pets or kids")),
                       "Is my pothos safe around my cat?")
        self.assertEqual(decision["status"], "ready_for_question")
        self.assertEqual(decision["safety_flags"], [
            {"layer": "policy", "category": "risk_topic", "detail": "plants toxic to pets or kids"}])
        self.assertTrue(decision["question"]["safety_flagged"])


class FailureTests(unittest.TestCase):
    """Empty text, invalid model output, API errors, decision shape and log hygiene."""
    def test_empty_text_asks_for_words_without_model_calls(self):
        """None, empty or blank text asks for words with no model call at all."""
        for text in (None, "", "   \n"):
            with self.subTest(text=text):
                fake = FakeLLM()
                decision = run(fake, text)
                self.assertEqual(decision, {
                    "status": "awaiting_clarification", "category": "needs_clarification", "service_kind": None,
                    "confidence": None, "reason": "No text in the message, asks for a description in words",
                    "prompt_version": "triage-v4+sweetlife-v2", "model": None, "safety_flags": [],
                    "question": None,
                    "clarification": {"round": 1, "prompt": SWEETLIFE_FLORA["empty_text_prompt"]},
                    "outbound": {"type": "clarification", "text": SWEETLIFE_FLORA["empty_text_prompt"]}})
                self.assertEqual(fake.calls, [])

    def test_invalid_output_twice_goes_to_creator(self):
        """Invalid classify output twice goes to creator_decision and keeps earlier moderation flags."""
        fake = FakeLLM(llm.InvalidOutput("not_json"), llm.InvalidOutput("bad_category"), flagged={"violence": 0.9})
        decision = run(fake)
        self.assertEqual(decision, {
            "status": "creator_decision", "category": None, "service_kind": None, "confidence": None,
            "reason": "Model returned invalid output twice", "prompt_version": "triage-v4+sweetlife-v2",
            "model": "test-model",
            "safety_flags": [{"layer": "moderation", "category": "violence", "detail": None}],
            "question": None, "clarification": None, "outbound": None})
        self.assertEqual(fake.names(), ["moderate", "classify", "classify"])

    def test_invalid_output_once_is_retried(self):
        """One invalid classify output is retried and the second answer is used."""
        fake = FakeLLM(llm.InvalidOutput("not_json"), result())
        self.assertEqual(run(fake)["status"], "ready_for_question")

    def test_clarification_failing_twice_goes_to_creator(self):
        """If the clarification text fails twice, the creator decides and nothing is sent."""
        fake = FakeLLM(result("needs_clarification", 0.9),
                       clarifications=(llm.InvalidOutput("bad_clarification"),) * 2)
        decision = run(fake, "why is it yellow")
        self.assertEqual((decision["status"], decision["category"], decision["reason"]),
                         ("creator_decision", "needs_clarification", "Model failed to write a clarification twice"))
        self.assertEqual((decision["clarification"], decision["outbound"]), (None, None))

    def test_api_errors_raise(self):
        """Moderation and OpenRouter API errors raise LLMError instead of returning a decision."""
        error = llm.LLMError("openai", 503, "server_error")
        with self.assertRaises(llm.LLMError):
            run(FakeLLM(moderation_error=error))
        with self.assertRaises(llm.LLMError):
            run(FakeLLM(llm.LLMError("openrouter", 429, "rate_limited")))

    def test_every_decision_has_the_same_shape(self):
        """Every kind of decision has exactly the same keys."""
        cases = [FakeLLM(result(c, 0.9, service_kind="platform" if c == "service_request" else None))
                 for c in CATEGORIES]
        cases += [FakeLLM(flagged={"self-harm/intent": 0.9}), FakeLLM(llm.InvalidOutput("x"), llm.InvalidOutput("x"))]
        for fake in cases:
            self.assertEqual(set(run(fake)), DECISION_KEYS)

    def test_logs_never_contain_dm_text(self):
        """triage logs never contain DM text, recent messages or clarification text."""
        secret = "my neighbour Priya at 555-0100 has a sad fern"
        with self.assertLogs("triage", level="INFO") as logs:
            run(FakeLLM(result("needs_clarification", 0.9)), secret, ["earlier private note"])
        output = "\n".join(logs.output)
        self.assertIn("status=awaiting_clarification", output)
        for fragment in ("Priya", "555-0100", "fern", "earlier private note", CLARIFY_TEXT):
            self.assertNotIn(fragment, output)


class ReassessTests(unittest.TestCase):
    """reassess routes clarification replies correctly across rounds 1 and 2."""
    def test_clear_after_round_one_is_ready_with_combined_question(self):
        """A reply that makes the question clear gives ready_for_question with original plus reply as question_text."""
        fake = FakeLLM(result())
        decision = rerun(fake, "why are the tips brown", [ROUND_1])
        self.assertEqual(decision, {
            "status": "ready_for_question", "category": "expert_question", "service_kind": None,
            "confidence": 0.94, "reason": "Asks about crispy calathea leaf tips",
            "prompt_version": "triage-v4+sweetlife-v2", "model": "test-model", "safety_flags": [],
            "question": {"question_text": "why are the tips brown\na calathea, north window, I water every week",
                         "safety_flagged": False},
            "clarification": None, "outbound": None})
        self.assertEqual(fake.calls[0], ("moderate", "a calathea, north window, I water every week"))
        self.assertEqual(fake.calls[1][1], "why are the tips brown")
        self.assertEqual(fake.calls[1][3], [{"round": 1, "prompt": CLARIFY_TEXT,
                                             "reply": "a calathea, north window, I water every week"}])

    def test_still_vague_after_round_one_asks_round_two(self):
        """Still vague after round 1 asks round 2, passing the earlier rounds to the clarification writer."""
        fake = FakeLLM(result("needs_clarification", 0.9), clarifications=("How long has it been happening?",))
        decision = rerun(fake, "why are the tips brown", [ROUND_1], ["hi"])
        self.assertEqual(decision["status"], "awaiting_clarification")
        self.assertEqual(decision["clarification"], {"round": 2, "prompt": "How long has it been happening?"})
        self.assertEqual(decision["outbound"], {"type": "clarification", "text": "How long has it been happening?"})
        self.assertEqual(decision["prompt_version"], "triage-v4+clarify-v4+sweetlife-v2")
        clarify = fake.calls[-1]
        self.assertEqual((clarify[0], clarify[1], clarify[2], len(clarify[3])),
                         ("clarify", "why are the tips brown", ["hi"], 1))

    def test_still_vague_after_round_two_goes_to_creator(self):
        """Still vague after round 2 goes to creator_decision without another question; rounds are sorted."""
        fake = FakeLLM(result("needs_clarification", 0.9))
        decision = rerun(fake, "why are the tips brown", [ROUND_2, ROUND_1])
        self.assertEqual((decision["status"], decision["category"], decision["reason"]),
                         ("creator_decision", "needs_clarification", "Still unclear after 2 clarification rounds"))
        self.assertEqual((decision["clarification"], decision["outbound"], decision["question"]), (None, None, None))
        self.assertEqual(fake.names(), ["moderate", "classify"])
        self.assertEqual([r["round"] for r in fake.calls[1][3]], [1, 2])
        self.assertEqual(fake.calls[0], ("moderate", "about two weeks"))

    def test_clear_after_round_two_joins_every_reply(self):
        """question_text joins recent messages, the original and every reply in order."""
        decision = rerun(FakeLLM(result()), "why are the tips brown", [ROUND_1, ROUND_2], ["hey"])
        self.assertEqual(decision["question"]["question_text"],
                         "hey\nwhy are the tips brown\na calathea, north window, I water every week\nabout two weeks")

    def test_reply_is_screened_before_classify(self):
        """The newest reply is moderated and checked for blocked terms before classify."""
        severe = FakeLLM(flagged={"self-harm/intent": 0.9})
        decision = rerun(severe, "why are the tips brown", [{**ROUND_1, "reply": "a reply in crisis"}])
        self.assertEqual((decision["status"], decision["outbound"]["text"]),
                         ("blocked", SWEETLIFE_FLORA["crisis_text"]))
        self.assertEqual(severe.names(), ["moderate"])
        rules = FakeLLM()
        decision = rerun(rules, "why are the tips brown", [{**ROUND_1, "reply": "kys"}])
        self.assertEqual((decision["status"], decision["safety_flags"][-1]["layer"]), ("blocked", "rules"))
        self.assertEqual(rules.names(), ["moderate"])

    def test_mild_flag_on_reply_is_kept(self):
        """A mild moderation flag on the reply carries into the decision and marks the question."""
        decision = rerun(FakeLLM(result(), flagged={"violence": 0.8}), "why are the tips brown", [ROUND_1])
        self.assertEqual(decision["safety_flags"], [{"layer": "moderation", "category": "violence", "detail": None}])
        self.assertTrue(decision["question"]["safety_flagged"])

    def test_empty_reply_and_original_skip_moderation(self):
        """Empty reply and original skip moderation and still classify."""
        fake = FakeLLM(result("needs_clarification", 0.9))
        decision = rerun(fake, None, [{**ROUND_1, "reply": None}])
        self.assertEqual(decision["clarification"]["round"], 2)
        self.assertEqual(fake.names(), ["classify", "clarify"])
        self.assertEqual(fake.calls[0][1], "")

    def test_social_reply_closes_and_service_reply_routes(self):
        """A social reply closes the message and a service reply routes it with its kind."""
        self.assertEqual(rerun(FakeLLM(result("social", 0.95)), "why brown", [ROUND_1])["status"], "closed_no_action")
        decision = rerun(FakeLLM(result("service_request", 0.95, service_kind="platform")), "why brown", [ROUND_1])
        self.assertEqual((decision["status"], decision["service_kind"]), ("service_routed", "platform"))

    def test_invalid_output_twice_goes_to_creator(self):
        """Invalid classify output twice in reassess goes to creator_decision."""
        fake = FakeLLM(llm.InvalidOutput("not_json"), llm.InvalidOutput("not_json"))
        decision = rerun(fake, "why brown", [ROUND_1])
        self.assertEqual((decision["status"], decision["reason"]),
                         ("creator_decision", "Model returned invalid output twice"))

    def test_api_error_raises(self):
        """An API error during reassess raises LLMError."""
        with self.assertRaises(llm.LLMError):
            rerun(FakeLLM(llm.LLMError("openrouter", 500)), "why brown", [ROUND_1])

    def test_reassess_requires_a_round(self):
        """reassess with no rounds raises ValueError instead of guessing."""
        for rounds in (None, []):
            with self.assertRaises(ValueError):
                rerun(FakeLLM(), "why brown", rounds)

    def test_reassess_logs_never_contain_dm_text(self):
        """reassess logs never contain the original or reply text."""
        with self.assertLogs("triage", level="INFO") as logs:
            rerun(FakeLLM(result()), "secret original about Priya", [{**ROUND_1, "reply": "reply with 555-0100"}])
        output = "\n".join(logs.output)
        self.assertIn("stage=reassess status=ready_for_question", output)
        for fragment in ("Priya", "555-0100", "secret original"):
            self.assertNotIn(fragment, output)


def completion(content, model="google/gemini-3.1-flash-lite"):
    """Build a fake OpenRouter chat completion response with usage."""
    return {"model": model, "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.00005}}


VALID = {"category": "service_request", "service_kind": "out_of_domain", "confidence": 0.9,
         "reason": "Asks about fitness", "risk_flag": False, "risk_reason": ""}


@patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter", "OPENAI_API_KEY": "test-openai"})
class LlmTests(unittest.TestCase):
    """llm.py request building and response validation, with HTTP patched out."""
    def test_classify_request_uses_strict_schema_and_reads_model_at_call_time(self):
        """classify sends a strict schema at temperature 0, reads TRIAGE_MODEL and the key at call time."""
        with patch.dict(os.environ, {"TRIAGE_MODEL": "google/other-model"}), \
                patch("llm._json_request", return_value=completion(json.dumps(VALID))) as request:
            classified = llm.classify("protein powder?", ["hi"], SWEETLIFE_FLORA)
        service, url, headers, body = request.call_args.args
        self.assertEqual((service, url), ("openrouter", llm.OPENROUTER_URL))
        self.assertEqual(headers["Authorization"], "Bearer test-openrouter")
        self.assertEqual((body["model"], body["temperature"]), ("google/other-model", 0))
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(body["response_format"]["json_schema"]["schema"]["properties"]["risk_reason"]["enum"],
                         ["", *SWEETLIFE_FLORA["risk_topics"]])
        self.assertIn('"hi"', body["messages"][1]["content"])
        self.assertEqual((classified["category"], classified["service_kind"], classified["risk_reason"]),
                         ("service_request", "out_of_domain", None))

    def test_classify_rejects_invalid_output(self):
        """Bad JSON, categories, confidence, service_kind or risk_reason raise InvalidOutput and log only a code."""
        bad = ["not json", json.dumps([]), json.dumps({**VALID, "category": "question"}),
               json.dumps({**VALID, "confidence": 1.4}), json.dumps({**VALID, "confidence": True}),
               json.dumps({**VALID, "service_kind": ""}),
               json.dumps({**VALID, "category": "expert_question", "risk_flag": True, "risk_reason": "made up"})]
        for content in bad:
            with self.subTest(content=content):
                with patch("llm._json_request", return_value=completion(content)), \
                        self.assertLogs("llm", level="WARNING") as logs:
                    with self.assertRaises(llm.InvalidOutput):
                        llm.classify("text", [], SWEETLIFE_FLORA)
                self.assertIn("stage=classify FAIL error_type=invalid_output", logs.output[0])

    def test_rounds_are_sent_after_the_original_message(self):
        """Clarification rounds are rendered after the original message, with DM text JSON-quoted."""
        with patch("llm._json_request", return_value=completion(json.dumps(VALID))) as request:
            llm.classify("why brown", ["hi"], SWEETLIFE_FLORA, [ROUND_1])
        user = request.call_args.args[3]["messages"][1]["content"]
        self.assertEqual(user.splitlines(), [
            "Earlier messages, oldest first:", '1. "hi"', "Original message:", '"why brown"',
            "Clarification so far:", f'Round 1 question from the creator: "{CLARIFY_TEXT}"',
            'Round 1 reply from the follower: "  a calathea, north window, I water every week  "'])

    def test_moderate_returns_flagged_categories_with_scores(self):
        """moderate returns only flagged categories with their scores and uses the OpenAI key."""
        response = {"results": [{"flagged": True,
                                 "categories": {"violence": True, "self-harm/intent": False, "harassment": True},
                                 "category_scores": {"violence": 0.4, "self-harm/intent": 0.6, "harassment": 0.9}}]}
        with patch("llm._json_request", return_value=response) as request:
            self.assertEqual(llm.moderate("text"), {"harassment": 0.9, "violence": 0.4})
        self.assertEqual(request.call_args.args[3], {"model": "omni-moderation-latest", "input": "text"})
        self.assertEqual(request.call_args.args[2]["Authorization"], "Bearer test-openai")

    def test_clarification_must_be_short_plain_text(self):
        """Clarifications must be non-empty, under 200 characters and never mention media."""
        with patch("llm._json_request", return_value=completion(f"  {CLARIFY_TEXT}\n")):
            self.assertEqual(llm.write_clarification("why yellow", [], SWEETLIFE_FLORA), CLARIFY_TEXT)
        for content in ("", "   ", None, "x" * 200, "Which plant is it? Could you send a photo of the leaves?",
                        "Can you share a quick video?"):
            with patch("llm._json_request", return_value=completion(content)), \
                    self.assertLogs("llm", level="WARNING") as logs:
                with self.assertRaises(llm.InvalidOutput):
                    llm.write_clarification("why yellow", [], SWEETLIFE_FLORA)
            self.assertNotIn("x" * 20, "\n".join(logs.output))

    def test_missing_key_fails_before_any_request(self):
        """A missing API key raises RuntimeError before any HTTP request."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), patch("llm.urlopen") as urlopen:
            with self.assertRaises(RuntimeError):
                llm.moderate("text")
        urlopen.assert_not_called()

    def test_http_and_network_errors_become_llm_errors_with_ten_second_timeout(self):
        """HTTP and network errors become LLMError, and requests use the 10 second timeout."""
        body = BytesIO(b'{"error":{"message":"Rate limited","code":429}}')
        error = HTTPError(llm.OPENROUTER_URL, 429, "Too Many Requests", {}, body)
        with patch("llm.urlopen", side_effect=error) as urlopen:
            with self.assertRaises(llm.LLMError) as raised:
                llm.classify("text", [], SWEETLIFE_FLORA)
        self.assertEqual((raised.exception.service, raised.exception.status, raised.exception.code),
                         ("openrouter", 429, 429))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)
        with patch("llm.urlopen", side_effect=TimeoutError()):
            with self.assertRaises(llm.LLMError) as raised:
                llm.moderate("text")
        self.assertEqual((raised.exception.service, raised.exception.code), ("openai", "TimeoutError"))


if __name__ == "__main__":
    unittest.main()
