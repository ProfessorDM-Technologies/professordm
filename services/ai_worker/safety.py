"""Safety screening shared by triage (inbound DMs) and draft (AI answers).

Safety layers 1 (OpenAI moderation) and 2 (blocked terms) live here so both
checkpoints apply the same thresholds and the same blocked list: triage
screens each inbound DM (checkpoint 1), and draft screens the answer the model
wrote before it reaches the creator (checkpoint 2).

Contents:
    SEVERE, SCORED_SEVERE, MILD_FLAG_THRESHOLD, SEVERE_FLAG_THRESHOLD,
    BLOCKED_TERMS
        What blocks, what only flags, and the base blocked phrases.
    flag(layer, category, detail=None)
        Builds one safety flag entry.
    blocked_term(text, profile)
        Checks text against the base and creator blocked terms.
    screen(text, profile, *, moderate)
        Runs both layers and reports what was found. Callers decide what a
        block means for them (triage builds a decline decision).

Depends on:
    The standard library only (re). The moderation call is passed in as
    `moderate` (callers pass their own llm.moderate), so this module never
    imports llm and the tests that fake llm in triage still reach the fake.

Never does:
    - Make HTTP calls itself, or pick decline texts and statuses (that is the
      caller's decision).
    - Log anything. The moderation call logs its own line (category names and
      latency only), and callers log the outcome.
    - Put text into a flag. A flag's detail is only ever None or one of the
      profile's risk topics, because flags are stored and shown to reviewers.
"""

import re


# A non-blocking moderation category only becomes a safety flag at this score
# or above (OpenAI must also have flagged it). Without this, pest questions like
# "how do I kill the fungus gnats" were flagged for violence at 0.40 and sent to
# the creator's Moderation tab. 0.5 cleared most pest phrases we probed
# (violence 0.12 to 0.45) while keeping clear harassment (0.65 to 0.89). The
# most graphic ones ("no survivors", "bug homicide") scored about 0.52 and still
# get a mild flag, which only marks the question for review. Calibrated on
# synthetic data only; revisit with real DMs.
MILD_FLAG_THRESHOLD = 0.5

# The threatening categories in SCORED_SEVERE only block at this score or
# above. Below it they are treated like any other category (flagged at
# MILD_FLAG_THRESHOLD). Chosen so "Answer me or I'll make you regret it"
# (harassment/threatening 0.52) still blocks. Real threats that score lower
# (0.22 to 0.33 in the test split) are still caught by the classifier as
# safety_concern and reach the creator. Calibrated on synthetic data only.
SEVERE_FLAG_THRESHOLD = 0.5

# OpenAI moderation categories that block the message outright: no
# classification, a polite decline (or crisis_text for self-harm), and a
# safety flag. These are the categories where an automated reply or a paid
# answer must never happen.
# illicit/violent is deliberately NOT here. It fires on pest-killing language
# ("whats the best way to nuke them?? 💀" scored 0.80), and blocking would send
# a decline to a follower asking about bugs. It is flag-only now: a genuinely
# harmful request (a ricin question scored 0.62) still gets a moderation flag,
# and the classifier labels it safety_concern, so it reaches creator_decision.
SEVERE = {
    "self-harm/intent",
    "self-harm/instructions",
    "sexual/minors",
    "harassment/threatening",
    "hate/threatening",
}

# The subset of SEVERE that only blocks at SEVERE_FLAG_THRESHOLD. self-harm/*
# and sexual/minors block on OpenAI's own flag at any score, because missing
# one costs far more than an occasional false block.
SCORED_SEVERE = {"harassment/threatening", "hate/threatening"}

# Base blocked phrases for every creator, matched case-insensitively as whole
# words with any whitespace between words. A match blocks with a decline.
# Kept short on purpose: moderation and the classifier cover most abuse, and
# slurs are left to moderation so they do not live in source. "doxx" and
# "doxxing" were removed so a victim reporting it is not blocked. Each
# creator's own terms go in the profile's extra_blocked_terms. Placeholder
# until Kristin and Karthik sign off the final list.
BLOCKED_TERMS = (
    "kill yourself",
    "kys",
    "send nudes",
    "child porn",
)


def flag(layer, category, detail=None):
    """Build one safety flag entry for the decision.

    Args:
        layer (str): "moderation" (OpenAI moderation), "rules" (blocked terms)
            or "policy" (the classifier's risk_flag or a safety_concern label).
            These match the safety_flags.layer check in the schema.
        category (str): What was found, for example "violence",
            "blocked_term", "risk_topic" or "safety_concern".
        detail (str | None): Extra context. Only ever None or one of the
            profile's risk topics, never DM text, because flags are stored and
            shown to reviewers.

    Returns:
        dict: {"layer": str, "category": str, "detail": str | None}

    Side effects: none.
    """
    return {"layer": layer, "category": category, "detail": detail}


def blocked_term(text, profile):
    """Check the DM against the base and creator blocked terms (safety layer 2).

    Matching is case-insensitive and whole-word: "kys" matches "kys" but not
    "skys". Spaces inside a term match any run of whitespace, so "kill
    yourself" also matches "KILL   yourself". Lookarounds are used instead of
    \\b so terms that start or end with punctuation still match correctly.

    Args:
        text (str): The DM text (already stripped).
        profile (dict): The creator profile; its extra_blocked_terms are added
            to BLOCKED_TERMS.

    Returns:
        bool: True if any term matches.

    Side effects: none.
    """
    terms = [*BLOCKED_TERMS, *profile.get("extra_blocked_terms", [])]
    pattern = "|".join(re.escape(term.strip()).replace(r"\ ", r"\s+") for term in terms if term.strip())
    return bool(pattern) and re.search(rf"(?<!\w)(?:{pattern})(?!\w)", text, re.IGNORECASE) is not None


def screen(text, profile, *, moderate):
    """Run safety layers 1 (moderation) and 2 (blocked terms) on one text.

    Layer 1 comes first: a severe moderation hit is the reason for a block,
    and the blocked terms are then not checked (the same order triage has
    always used, so its flags are unchanged). Without a severe hit, a blocked
    term match adds a "rules" flag after the moderation flags.

    Args:
        text (str): The text to screen: a new DM, the newest clarification
            reply, or an AI answer. Already stripped.
        profile (dict): The creator profile (for extra_blocked_terms).
        moderate (callable[[str], dict[str, float]]): The moderation call,
            normally the caller's llm.moderate. It returns only the categories
            OpenAI flagged, each mapped to its score. Required, so a caller
            whose llm is a fake in tests never reaches the network.

    Returns:
        dict: {"severe": list[str], "flags": list[dict], "blocked_term": bool,
        "crisis": bool}.
            severe        the SEVERE categories that block, in moderation
                          order; non-empty means the text must stop here.
            flags         flag() entries, in moderation order: every severe
                          hit, every other hit at MILD_FLAG_THRESHOLD or
                          above, then {"layer": "rules", "category":
                          "blocked_term"} when a term matched.
            blocked_term  True when a blocked term matched (checked only
                          when nothing was severe).
            crisis        True when a severe hit is self-harm, so the caller
                          sends crisis resources (988) instead of a decline.

    Raises:
        Whatever moderate raises (llm.LLMError on an outage). Not caught here,
        so an unscreened text is never treated as clean.

    Side effects: one moderate() call.
    """
    hits = moderate(text)
    # hits holds only the categories OpenAI flagged, mapped to their scores.
    severe = [category for category, score in hits.items() if category in SEVERE
              and (category not in SCORED_SEVERE or score >= SEVERE_FLAG_THRESHOLD)]
    # Severe hits are always recorded; anything else needs MILD_FLAG_THRESHOLD
    # so pest-killing language does not flag every pest question.
    flags = [flag("moderation", category) for category, score in hits.items()
             if category in severe or score >= MILD_FLAG_THRESHOLD]
    matched = not severe and blocked_term(text, profile)
    if matched:
        flags.append(flag("rules", "blocked_term"))
    return {"severe": severe, "flags": flags, "blocked_term": matched,
            "crisis": any(category.startswith("self-harm") for category in severe)}
