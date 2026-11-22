"""The final answer screen (checkpoint 3): one decision on the exact text about to be sent.

SAF01 says the exact final outbound text must be screened, including the
creator's edits and her manual replies. A safe AI draft can become unsafe
after an edit, so the send API calls this screen on every text right before
it goes out. This module turns that text into one response dict (the shared
contract in docs/final-answer-screen.md): PASS, HOLD or BLOCK, with the
findings behind it.

Entry point:
    screen_final(text, *, question_text=None, profile, moderate, check_rules,
                 clock=time.monotonic, deadline_seconds=SCREEN_DEADLINE_SECONDS)
        Called by screen_handler.lambda_handler for each request.

Flow:
    hash the text and build check_version; start two tasks at the same time
    (layers 1 and 2: safety.screen; layer 3: the answer-rules check); wait
    for both until the deadline; combine every finding into one decision.

    Decision order: BLOCK (a severe moderation hit or a blocked term), then
    HOLD for the system (a check failed or did not finish), then HOLD for the
    creator (a mild moderation hit or a broken answer rule), then PASS.

Depends on:
    safety   screen (layers 1 and 2), blocked_term and flag, shared with
             triage's checkpoint 1 and draft's checkpoint 2, so the thresholds
             and the blocked list are the same everywhere.
    prompts  answer_rule_ids, prompt_version and FINAL_CHECK_VERSION.
    The standard library (concurrent.futures, hashlib, logging, time).
    The two model calls are passed in as `moderate` and `check_rules`
    (normally llm.moderate and llm.check_answer_rules), so this module makes
    no HTTP calls and tests never reach the network.

Never does:
    - Make HTTP calls itself, read or write the database, or send anything.
    - Strip or change the text. It is hashed and screened exactly as given.
    - Put text into the response. categories holds moderation category names
      and "blocked_term"; rules holds the creator's own rule text (config,
      not message text); a flag's detail is None, one of the profile's risk
      topics or an answer-rule id like "R2".
    - Log the text, the question or a key.
"""

from concurrent.futures import ThreadPoolExecutor, wait
import hashlib
import logging
import time

import safety
from prompts import FINAL_CHECK_VERSION, answer_rule_ids, prompt_version


# Seconds the whole screen may take, measured from the start of screen_final.
# Anything not finished by then counts as a check that did not run. The
# numbers around it, all in seconds:
#     11  this deadline
#     15  the screen Lambda's own timeout (infra/ai-worker.yaml, Karthik)
#     14  the send Lambda's read timeout when it invokes the screen
#     28  the send Lambda's timeout
# So the screen answers before its own function is killed (15), the caller
# stops waiting just before that (14), and the send Lambda still has time to
# act on the answer (28). The deadline is enforced here and never by the
# per-call timeouts: each model call may take up to llm.TIMEOUT (10 s) and the
# rules check may be called twice, which together would overrun every number
# above.
SCREEN_DEADLINE_SECONDS = 11

# The rules check is retried after invalid output only when at least this many
# seconds remain before the deadline. A typical rules call takes 0.3 to 2
# seconds, so 3 gives a retry a fair chance to finish; one started later would
# mostly run past the deadline and be thrown away.
RULES_RETRY_MIN_SECONDS = 3

# The order of reason_codes in the response, strongest first. Fixed so the
# same findings always produce the same list.
REASON_ORDER = ("moderation_severe", "blocked_term", "moderation_mild", "answer_rule", "check_unavailable")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _screen_task(text, profile, moderate):
    """Run safety layers 1 and 2 on the text (one of the two parallel tasks).

    Args:
        text (str): The exact text, unchanged.
        profile (dict): The creator profile (for extra_blocked_terms).
        moderate (callable[[str], dict[str, float]]): The moderation call.

    Returns:
        dict: safety.screen's result ({"severe", "flags", "blocked_term",
        "crisis"}).

    Side effects: one moderate() call.
    """
    return safety.screen(text, profile, moderate=moderate)


def _rules_task(text, question_text, profile, check_rules):
    """Run safety layer 3, the answer-rules check (the other parallel task).

    Args:
        text (str): The exact text, unchanged.
        question_text (str | None): The follower's question, or None.
        profile (dict): The creator profile.
        check_rules (callable): check_rules(text, question_text, profile),
            normally llm.check_answer_rules with its timeout bound.

    Returns:
        dict: The check's result, with at least "broken_rules" (rule ids),
        "risk_topics" and "model".

    Side effects: one check_rules() call.
    """
    return check_rules(text, question_text, profile)


def _combine(text, profile, screened, checked):
    """Turn the two checks' results into the contract's response.

    Every finding is listed whatever the decision (contract v2.1): callers
    branch on decision and next_actor only, and show the rest.

    Args:
        text (str): The exact text (for the hash).
        profile (dict): The creator profile (answer_rules, risk_topics,
            version).
        screened (dict): safety.screen's result.
        checked (dict): The answer-rules result.

    Returns:
        dict: {"decision", "next_actor", "reason_codes", "categories",
        "rules", "flags", "text_sha256", "check_version", "model"}.
            reason_codes  in REASON_ORDER.
            categories    moderation categories in moderation's order, then
                          "blocked_term".
            rules         {"id", "text"} per broken rule, in rule order.
            flags         moderation flags, the blocked-term flag, one
                          answer_rule flag per broken rule, one risk_topic
                          flag per topic in the profile's order.

    Side effects: none.
    """
    severe = screened["severe"]
    moderation_flags = [entry for entry in screened["flags"] if entry["layer"] == "moderation"]
    # A mild hit is any flagged moderation category that did not block.
    mild = [entry["category"] for entry in moderation_flags if entry["category"] not in severe]
    blocked = screened["blocked_term"]
    rule_text = dict(zip(answer_rule_ids(profile), profile["answer_rules"]))
    # Read in the profile's order, which also drops duplicates.
    broken = [rule_id for rule_id in rule_text if rule_id in checked["broken_rules"]]
    topics = [topic for topic in profile["risk_topics"] if topic in checked["risk_topics"]]

    found = {"moderation_severe": bool(severe), "blocked_term": blocked, "moderation_mild": bool(mild),
             "answer_rule": bool(broken), "check_unavailable": False}
    if severe or blocked:
        decision, next_actor = "BLOCK", "creator"
    elif mild or broken:
        decision, next_actor = "HOLD", "creator"
    else:
        decision, next_actor = "PASS", "none"

    return {
        "decision": decision,
        "next_actor": next_actor,
        "reason_codes": [code for code in REASON_ORDER if found[code]],
        "categories": [entry["category"] for entry in moderation_flags] + (["blocked_term"] if blocked else []),
        "rules": [{"id": rule_id, "text": rule_text[rule_id]} for rule_id in broken],
        "flags": (moderation_flags
                  + ([safety.flag("rules", "blocked_term")] if blocked else [])
                  + [safety.flag("policy", "answer_rule", rule_id) for rule_id in broken]
                  + [safety.flag("policy", "risk_topic", topic) for topic in topics]),
        # The caller sends this same string and echoes this hash to confirm a
        # HOLD, so it covers the text exactly as given: no stripping.
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "check_version": prompt_version(profile, FINAL_CHECK_VERSION),
        "model": checked.get("model"),
    }


def screen_final(text, *, question_text=None, profile, moderate, check_rules, clock=time.monotonic,
                 deadline_seconds=SCREEN_DEADLINE_SECONDS):
    """Screen the exact final text and return the contract's decision.

    Layers 1 and 2 (moderation and blocked terms) and layer 3 (the creator's
    answer rules) run at the same time on two threads, under one deadline.

    Args:
        text (str): The exact text that will be sent. Never stripped.
        question_text (str | None): The follower's question, or None for a
            manual reply. Some answer rules depend on it.
        profile (dict): The creator profile (prompts.profile_for).
        moderate (callable[[str], dict[str, float]]): The moderation call,
            normally llm.moderate.
        check_rules (callable): check_rules(text, question_text, profile),
            normally llm.check_answer_rules with its timeout bound. Returns a
            dict with "broken_rules", "risk_topics" and "model".
        clock (callable[[], float]): Seconds, monotonic. Tests pass a fake.
        deadline_seconds (float): The overall deadline. Tests pass a short
            one so they run fast.

    Returns:
        dict: The contract's response without latency_ms (the handler adds
        it); see _combine for the fields.

    Side effects: one moderation call and one answer-rules call, each on its
    own thread.
    """
    deadline = clock() + deadline_seconds
    # No `with` block: its exit waits for every thread, and a slow provider
    # must not hold the response past the deadline.
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="final-screen")
    try:
        screen_future = executor.submit(_screen_task, text, profile, moderate)
        rules_future = executor.submit(_rules_task, text, question_text, profile, check_rules)
        wait([screen_future, rules_future], timeout=max(0.0, deadline - clock()))
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return _combine(text, profile, screen_future.result(), rules_future.result())
