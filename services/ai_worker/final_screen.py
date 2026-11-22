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

    Failing closed (SAF05): a check that raises, returns something outside its
    vocabulary, gives invalid output twice or is not finished by the deadline
    is "unavailable". The text is then never treated as clean; the only
    stronger outcome is a BLOCK found by a check that did finish.

Depends on:
    safety   screen (layers 1 and 2), blocked_term and flag, shared with
             triage's checkpoint 1 and draft's checkpoint 2, so the thresholds
             and the blocked list are the same everywhere. The blocked-term
             match is always run here as well, because safety.screen skips it
             after a severe hit or when moderation raises.
    prompts  answer_rule_ids, prompt_version and FINAL_CHECK_VERSION.
    llm      only its two exception types (LLMError, InvalidOutput), to tell
             an outage from invalid output.
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
    - Raise because a check failed. Every failure becomes check_unavailable.
    - Wait for a slow check past the deadline, or use a result that arrives
      after it. A thread still waiting on a provider is left to end at its
      own timeout and its result is thrown away.
    - Log the text, the question or a key. Its own lines carry only the
      stage and the error type.
"""

from concurrent.futures import ThreadPoolExecutor, wait
import hashlib
import logging
import time

import llm
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


def _failed(stage, kind):
    """Log one failed check and build its outcome.

    Args:
        stage (str): "screen" (layers 1 and 2) or "rules" (layer 3).
        kind (str): "llm_error", "invalid_output", "bad_result", "deadline",
            "config_error", or the class name of an unexpected exception.

    Returns:
        tuple[str, str]: ("failed", kind).

    Side effects: one log line with the stage and the kind only. A missing
    key is logged as an error (a configuration problem someone must fix);
    everything else as a warning.
    """
    if kind == "config_error":
        logger.error("Final screen config_error stage=%s", stage)
    else:
        logger.warning("Final screen stage=%s FAIL error_type=%s", stage, kind)
    return "failed", kind


def _kind(error):
    """Name a check's exception for the log, without its message.

    Args:
        error (Exception): What the check raised.

    Returns:
        str: "llm_error" for an outage or timeout, "invalid_output" for a
        reply that broke the schema, "config_error" for a missing key
        (RuntimeError), otherwise the exception's class name. Never the
        message, which could echo request content.

    Side effects: none.
    """
    if isinstance(error, llm.LLMError):
        return "llm_error"
    if isinstance(error, llm.InvalidOutput):
        return "invalid_output"
    if isinstance(error, RuntimeError):
        return "config_error"
    return type(error).__name__


def _screen_task(text, profile, moderate):
    """Run safety layers 1 and 2 on the text (one of the two parallel tasks).

    Args:
        text (str): The exact text, unchanged.
        profile (dict): The creator profile (for extra_blocked_terms).
        moderate (callable[[str], dict[str, float]]): The moderation call.

    Returns:
        tuple: ("ok", safety.screen's result) or ("failed", kind). It never
        raises: any exception from the moderation call is a failed check, so
        an unscreened text can never be mistaken for a clean one.

    Side effects: one moderate() call, and one log line on failure.
    """
    try:
        return "ok", safety.screen(text, profile, moderate=moderate)
    except Exception as error:  # fail closed on anything, including bugs
        return _failed("screen", _kind(error))


def _valid_rules(result, profile):
    """Say whether an answer-rules result holds only fixed vocabulary.

    The ids and topics go into stored flags, so this module checks them
    itself, whatever the injected check returned.

    Args:
        result (Any): What check_rules returned.
        profile (dict): The creator profile (answer_rules, risk_topics).

    Returns:
        bool: True for a dict whose "broken_rules" is a list of this
        profile's rule ids and whose "risk_topics" is a list of this
        profile's risk topics.

    Side effects: none.
    """
    if not isinstance(result, dict):
        return False
    broken, topics = result.get("broken_rules"), result.get("risk_topics")
    if not isinstance(broken, list) or not isinstance(topics, list):
        return False
    rule_ids = answer_rule_ids(profile)
    return (all(isinstance(rule_id, str) and rule_id in rule_ids for rule_id in broken)
            and all(isinstance(topic, str) and topic in profile["risk_topics"] for topic in topics))


def _rules_task(text, question_text, profile, check_rules, clock, deadline):
    """Run safety layer 3, the answer-rules check, with one retry on invalid output.

    Invalid output is usually a one-off, so it earns one retry, but only
    when at least RULES_RETRY_MIN_SECONDS remain before the deadline. An
    outage is never retried here: it would only add latency, and the creator
    can press send again.

    Args:
        text (str): The exact text, unchanged.
        question_text (str | None): The follower's question, or None.
        profile (dict): The creator profile.
        check_rules (callable): check_rules(text, question_text, profile),
            normally llm.check_answer_rules with its timeout bound.
        clock (callable[[], float]): The screen's clock.
        deadline (float): The screen's deadline, as a clock() value.

    Returns:
        tuple: ("ok", the check's result) or ("failed", kind). It never
        raises. kind is "invalid_output" after two invalid replies (or one,
        with no time to retry) and "bad_result" for a result outside the
        vocabulary (see _valid_rules), which is not retried.

    Side effects: one or two check_rules() calls, and one log line on
    failure.
    """
    for attempt in (1, 2):
        try:
            result = check_rules(text, question_text, profile)
        except llm.InvalidOutput:
            if attempt == 1 and deadline - clock() >= RULES_RETRY_MIN_SECONDS:
                continue
            return _failed("rules", "invalid_output")
        except Exception as error:  # fail closed on anything, including bugs
            return _failed("rules", _kind(error))
        if not _valid_rules(result, profile):
            return _failed("rules", "bad_result")
        return "ok", result


def _combine(text, profile, screened, checked):
    """Turn the two checks' results into the contract's response.

    Every finding is listed whatever the decision (contract v2.1): callers
    branch on decision and next_actor only, and show the rest.

    Args:
        text (str): The exact text (for the hash and the local term check).
        profile (dict): The creator profile (answer_rules, risk_topics,
            version).
        screened (dict | None): safety.screen's result, or None when layers
            1 and 2 failed or did not finish.
        checked (dict | None): The answer-rules result, or None when layer 3
            failed or did not finish.

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
            model         the model that served the rules check, or None
                          when that check gave no valid result.

    Side effects: none.
    """
    unavailable = screened is None or checked is None
    severe = screened["severe"] if screened else []
    moderation_flags = [entry for entry in screened["flags"] if entry["layer"] == "moderation"] if screened else []
    # A mild hit is any flagged moderation category that did not block.
    mild = [entry["category"] for entry in moderation_flags if entry["category"] not in severe]
    # The term match is checked here, not read from `screened`, for two
    # reasons. safety.screen skips it once a moderation hit is severe (the
    # order triage has always used), but this response lists every finding,
    # so the creator learns about the phrase and the threat together. And it
    # is a local regex, so it still runs when moderation is down or late: a
    # blocked term always means BLOCK (contract v2.1), and the creator is not
    # told "try again" about a text that can never be sent.
    blocked = safety.blocked_term(text, profile)
    rule_text = dict(zip(answer_rule_ids(profile), profile["answer_rules"]))
    # Read in the profile's order, which also drops duplicates.
    broken = [rule_id for rule_id in rule_text if rule_id in checked["broken_rules"]] if checked else []
    topics = [topic for topic in profile["risk_topics"] if topic in checked["risk_topics"]] if checked else []

    found = {"moderation_severe": bool(severe), "blocked_term": blocked, "moderation_mild": bool(mild),
             "answer_rule": bool(broken), "check_unavailable": unavailable}
    if severe or blocked:
        decision, next_actor = "BLOCK", "creator"
    elif unavailable:
        # Above HOLD/creator on purpose: a creator must not be able to
        # confirm past a check that did not run.
        decision, next_actor = "HOLD", "system"
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
        "model": checked.get("model") if checked else None,
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
        it); see _combine for the fields. Returned by the deadline at the
        latest. A check that failed or did not finish adds
        "check_unavailable" and makes the decision HOLD for the system,
        unless a check that did finish found a reason to BLOCK.

    Raises:
        Nothing for a failed check (see _screen_task and _rules_task).

    Side effects: one moderation call and one or two answer-rules calls, on
    two threads, and one log line per failed check. A call still running at
    the deadline is left to finish on its own thread; its result is never
    read.
    """
    deadline = clock() + deadline_seconds
    # No `with` block: its exit waits for every thread, and a slow provider
    # must not hold the response past the deadline.
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="final-screen")
    try:
        futures = {"screen": executor.submit(_screen_task, text, profile, moderate),
                   "rules": executor.submit(_rules_task, text, question_text, profile, check_rules, clock,
                                            deadline)}
        done, _ = wait(futures.values(), timeout=max(0.0, deadline - clock()))
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    # Only the futures that finished in time are read. `done` is a snapshot:
    # a task that completes a moment later is not in it, so a late result can
    # never change the response.
    results = {}
    for stage, future in futures.items():
        status, value = future.result() if future in done else _failed(stage, "deadline")
        results[stage] = value if status == "ok" else None
    return _combine(text, profile, results["screen"], results["rules"])
