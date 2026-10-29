"""Evaluate triage() against the golden set and report dev and test separately.

Runs the real triage() pipeline (moderation, blocked terms, classify,
clarification) on every row of eval/triage_golden.jsonl with the real model
APIs, then prints accuracy, per-category precision and recall, a 6x6
confusion matrix, every wrong prediction, safety flags, moderation scores for
safety items, routed statuses, a confidence-cutoff table, latency, tokens and
cost. Results are saved to eval/results/<timestamp>.json (git-ignored).

Usage:
    set -a; source .env; set +a
    uv run --python 3.11 python eval/eval_triage.py [--limit N] [--model ID]

Depends on: services/ai_worker (llm, prompts, triage), OPENAI_API_KEY and
OPENROUTER_API_KEY in the environment, and the standard library.

Never does: change prompts or thresholds, write to the golden set, or touch
the database. It refuses to run if any golden row copies a few-shot example
from the prompt, because that would inflate the scores.

Split rules: the prompt is tuned only on "dev". "test" is frozen and is never
used to change prompts.py; report it, don't tune on it.
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
# ai_worker uses flat imports (like the Lambda), so put it on the path.
sys.path.insert(0, str(HERE.parent / "services" / "ai_worker"))

import llm
from prompts import CATEGORIES, SWEETLIFE_FLORA, prompt_version
from triage import MILD_FLAG_THRESHOLD, SEVERE_FLAG_THRESHOLD, triage

# dev: rows the prompt was tuned on. test: frozen rows, reported but never tuned on.
SPLITS = ("dev", "test")
# Similarity (difflib ratio after normalizing) at which a golden row counts as a
# copy of a few-shot example. 0.9 catches copies with small edits
# ("My plant is dying, help!!") without flagging different DMs on the same topic.
NEAR_MATCH = 0.9
# Short column names so the confusion matrix fits in a terminal.
SHORT = {"expert_question": "expert", "needs_clarification": "clarify", "social": "social",
         "spam_irrelevant": "spam", "safety_concern": "safety", "service_request": "service"}


def load(path, limit):
    """Read and validate the golden set.

    Args:
        path (Path): The JSONL file, one row per line:
            {"id", "split", "text", "recent_messages", "label",
            "service_kind" (service_request only), "notes"}.
        limit (int | None): Keep only the first N rows (for quick runs).

    Returns:
        list[dict]: The rows, in file order.

    Raises:
        SystemExit: If a row has a split other than dev or test, or a label
            outside the 6 categories.

    Side effects: reads the file.
    """
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for row in rows:
        if row.get("split") not in SPLITS or row.get("label") not in CATEGORIES:
            sys.exit(f"{row.get('id')}: split must be dev or test and label one of the 6 categories")
    return rows[:limit] if limit else rows


def _normalize(text):
    """Lowercase, drop punctuation and collapse whitespace for fuzzy comparison.

    Args:
        text (str | None): Any text.

    Returns:
        str: The normalized text ("" for None).

    Side effects: none.
    """
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def few_shot_overlaps(rows, profile):
    """Find golden rows that copy, or nearly copy, a few-shot example.

    A golden row that matches a prompt example would score well for the wrong
    reason (the model saw the answer), so eval refuses to run.

    Args:
        rows (list[dict]): Golden rows (text and recent_messages are checked).
        profile (dict): The creator profile with the few-shot examples.

    Returns:
        list[tuple[str, int]]: (row id, example index) for every match with a
        similarity of NEAR_MATCH or more.

    Side effects: none.
    """
    shots = [_normalize(example["text"]) for example in profile["examples"]]
    overlaps = []
    for row in rows:
        for text in [row["text"], *(row.get("recent_messages") or [])]:
            golden = _normalize(text)
            for i, shot in enumerate(shots):
                if golden and SequenceMatcher(None, golden, shot).ratio() >= NEAR_MATCH:
                    overlaps.append((row["id"], i))
    return overlaps


# Per-thread scratch space for the row being predicted (rows run in parallel).
_calls = threading.local()
_openrouter = llm._openrouter


def _recording_openrouter(*args, **kwargs):
    """Wrap llm._openrouter to record token usage and cost for the current row.

    Args:
        *args, **kwargs: Passed through to llm._openrouter.

    Returns:
        tuple[str | None, dict]: Whatever llm._openrouter returns.

    Side effects: appends the call's meta to the thread-local _calls.meta.
    """
    content, meta = _openrouter(*args, **kwargs)
    _calls.meta.append(meta)
    return content, meta


# Patch llm so every OpenRouter call made inside triage() is recorded.
# llm looks these functions up at call time, so the patch takes effect.
llm._openrouter = _recording_openrouter
_json_request = llm._json_request


def _recording_json_request(service, url, headers, body, timeout=llm.TIMEOUT):
    """Wrap llm._json_request to record the full moderation scores for a row.

    llm.moderate only returns flagged categories; eval keeps every score so
    the thresholds can be sanity-checked on safety items.

    Args:
        service, url, headers, body, timeout: Passed through to llm._json_request.

    Returns:
        Any: The parsed response, unchanged.

    Side effects: sets the thread-local _calls.moderation for OpenAI calls.
    """
    response = _json_request(service, url, headers, body, timeout)
    if service == "openai" and isinstance(response, dict):
        result = (response.get("results") or [{}])[0]
        _calls.moderation = {k: round(v, 3) for k, v in (result.get("category_scores") or {}).items()}
    return response


# Patch the HTTP layer too, to capture the full moderation scores.
llm._json_request = _recording_json_request


def predict(row):
    """Run triage() on one golden row and collect what the report needs.

    Rate limits and transient API errors are retried here (eval only).
    Production code raises them so the backend can retry.

    Args:
        row (dict): One golden row.

    Returns:
        dict: {"id", "split", "label", "predicted", "status",
        "service_kind_label", "service_kind", "confidence", "reason",
        "risk_flag", "risk_reason", "safety_flags", "clarification",
        "moderation_scores", "latency_ms", "tokens", "cost", "model"}.
        confidence is 1.0 for decisions made without a model (blocked, empty
        text) and 0.0 when the model failed, so the cutoff table can sort them.

    Raises:
        llm.LLMError: If an API error persists after 5 attempts, or is not
            retryable.

    Side effects: real model calls (cost money) and sleeps between retries.
    """
    _calls.meta = []
    _calls.moderation = None
    started = time.monotonic()
    for attempt in range(5):
        try:
            decision = triage(row["text"], row.get("recent_messages") or [], SWEETLIFE_FLORA)
            break
        except llm.LLMError as error:
            # Retry rate limits (429), network errors (None) and server errors; anything
            # else (for example 401) is a real problem and stops the run.
            if attempt == 4 or error.status not in (429, None, 500, 502, 503):
                raise
            _calls.meta = []
            time.sleep(10 * (attempt + 1))
    risks = [f["detail"] for f in decision["safety_flags"] if f["category"] == "risk_topic"]
    confidence = decision["confidence"]
    # No model confidence: deterministic layers count as sure, failures as unsure.
    if confidence is None:
        confidence = 0.0 if decision["category"] is None else 1.0
    costs = [m["cost"] for m in _calls.meta if m["cost"] is not None]
    return {"id": row["id"], "split": row["split"], "label": row["label"],
            "predicted": decision["category"], "status": decision["status"],
            "service_kind_label": row.get("service_kind"), "service_kind": decision["service_kind"],
            "confidence": confidence, "reason": decision["reason"],
            "risk_flag": bool(risks), "risk_reason": risks[0] if risks else None,
            "safety_flags": decision["safety_flags"],
            "clarification": (decision["clarification"] or {}).get("prompt"),
            "moderation_scores": _calls.moderation,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "tokens": sum(m["prompt_tokens"] + m["completion_tokens"] for m in _calls.meta),
            "cost": sum(costs) if costs else None,
            "model": next((m["model"] for m in _calls.meta), None)}


def per_category(results):
    """Compute precision, recall and support for each category.

    Args:
        results (list[dict]): predict() outputs.

    Returns:
        dict[str, dict]: category -> {"precision": float | None,
        "recall": float | None, "support": int}. None means no predictions
        (precision) or no examples (recall) for that category.

    Side effects: none.
    """
    stats = {}
    for category in CATEGORIES:
        tp = sum(r["label"] == category and r["predicted"] == category for r in results)
        predicted = sum(r["predicted"] == category for r in results)
        actual = sum(r["label"] == category for r in results)
        stats[category] = {"precision": tp / predicted if predicted else None,
                           "recall": tp / actual if actual else None,
                           "support": actual}
    return stats


def confusion(results):
    """Build the 6x6 confusion matrix.

    Args:
        results (list[dict]): predict() outputs.

    Returns:
        dict[str, dict[str, int]]: true label -> predicted label -> count.
        A failed prediction (None) is not counted in any column.

    Side effects: none.
    """
    return {t: {p: sum(r["label"] == t and r["predicted"] == p for r in results)
                for p in CATEGORIES} for t in CATEGORIES}


def cutoff_table(results):
    """Show what each CONFIDENCE_CUTOFF from 0.05 to 0.95 would do.

    At each cutoff, predictions below it would go to the creator. A good
    cutoff keeps right answers above it and catches wrong answers below it.

    Args:
        results (list[dict]): predict() outputs.

    Returns:
        tuple[list[dict], float | None]: (rows, suggested). Each row is
        {"cutoff", "above", "below", "accuracy_above", "accuracy_below",
        "score"}, where score = right answers above + wrong answers below.
        suggested is the lowest cutoff with the best score, or None when no
        cutoff beats sending nothing to the creator.

    Side effects: none.
    """
    rows = []
    for step in range(1, 20):
        cutoff = round(step * 0.05, 2)
        above = [r for r in results if r["confidence"] >= cutoff]
        below = [r for r in results if r["confidence"] < cutoff]
        right_above = sum(r["label"] == r["predicted"] for r in above)
        wrong_below = sum(r["label"] != r["predicted"] for r in below)
        rows.append({"cutoff": cutoff, "above": len(above), "below": len(below),
                     "accuracy_above": right_above / len(above) if above else None,
                     "accuracy_below": (len(below) - wrong_below) / len(below) if below else None,
                     "score": right_above + wrong_below})
    best = max(rows, key=lambda row: (row["score"], -row["cutoff"]))
    return rows, best["cutoff"] if best["score"] > rows[0]["score"] else None


def summarize(results):
    """Collect the numbers saved for one split.

    Args:
        results (list[dict]): predict() outputs for one split.

    Returns:
        dict: {"examples", "accuracy", "service_kind_accuracy",
        "per_category", "confusion", "cutoffs", "suggested_cutoff"}.
        service_kind_accuracy counts only rows labeled and predicted
        service_request (None if there are none).

    Side effects: none.
    """
    cutoffs, suggested = cutoff_table(results)
    kinds = [r for r in results if r["service_kind_label"] and r["predicted"] == "service_request"]
    return {"examples": len(results),
            "accuracy": sum(r["label"] == r["predicted"] for r in results) / len(results),
            "service_kind_accuracy": (sum(r["service_kind"] == r["service_kind_label"] for r in kinds)
                                      / len(kinds) if kinds else None),
            "per_category": per_category(results), "confusion": confusion(results),
            "cutoffs": cutoffs, "suggested_cutoff": suggested}


def pct(value):
    """Format a fraction as a percentage for the report.

    Args:
        value (float | None): A fraction from 0 to 1.

    Returns:
        str: For example " 97.7%", or "  n/a" for None.

    Side effects: none.
    """
    return "  n/a" if value is None else f"{value * 100:5.1f}%"


def report(split, results, summary):
    """Print the full report for one split.

    Args:
        split (str): "dev" or "test".
        results (list[dict]): predict() outputs for the split.
        summary (dict): summarize() output for the split.

    Returns:
        None.

    Side effects: prints to stdout. Prints model reasons and ids, never DM text.
    """
    correct = sum(r["label"] == r["predicted"] for r in results)
    print(f"\n=== {split} split: {len(results)} examples ===")
    print(f"Overall accuracy: {correct}/{len(results)} = {pct(summary['accuracy']).strip()}")
    invalid = sum(r["predicted"] is None for r in results)
    if invalid:
        print(f"Invalid model outputs: {invalid}")
    kinds = [r for r in results if r["service_kind_label"] and r["predicted"] == "service_request"]
    if kinds:
        right = sum(r["service_kind"] == r["service_kind_label"] for r in kinds)
        print(f"service_kind correct: {right}/{len(kinds)} (of rows labeled and predicted service_request)")
    print("\nPer category        precision  recall  support")
    for category in CATEGORIES:
        s = summary["per_category"][category]
        print(f"  {category:<20}{pct(s['precision']):>8} {pct(s['recall']):>7} {s['support']:>8}")
    print("\nConfusion matrix (rows = true label, columns = predicted)")
    print(" " * 22 + "".join(f"{SHORT[c]:>9}" for c in CATEGORIES))
    for t in CATEGORIES:
        print(f"  {t:<20}" + "".join(f"{summary['confusion'][t][p]:>9}" for p in CATEGORIES))
    wrong = [r for r in results if r["label"] != r["predicted"]
             or (r["service_kind_label"] and r["predicted"] == "service_request"
                 and r["service_kind"] != r["service_kind_label"])]
    print(f"\nWrong predictions ({len(wrong)})")
    for r in wrong:
        kind = f" [{r['service_kind_label']} -> {r['service_kind']}]" if r["predicted"] == "service_request" else ""
        print(f"  {r['id']}: {r['label']} -> {r['predicted']}{kind} status={r['status']} "
              f"({r['confidence']:.2f}) {r['reason']}")
    flagged = [r for r in results if r["risk_flag"]]
    print(f"\nRisk flags ({len(flagged)}): " + ", ".join(f"{r['id']} [{r['risk_reason']}]" for r in flagged))
    other = [r for r in results if any(f["category"] != "risk_topic" for f in r["safety_flags"])]
    print(f"Other safety flags ({len(other)}): " + ", ".join(
        f"{r['id']} [{'/'.join(f['layer'] + ':' + f['category'] for f in r['safety_flags'] if f['category'] != 'risk_topic')}]"
        for r in other))
    safety = [r for r in results if "safety_concern" in (r["label"], r["predicted"])]
    print(f"\nModeration scores for safety_concern items (mild >= {MILD_FLAG_THRESHOLD}, "
          f"scored severe >= {SEVERE_FLAG_THRESHOLD})")
    for r in safety:
        scores = r["moderation_scores"]
        top = ", ".join(f"{k}={v:.3f}" for k, v in sorted(scores.items(), key=lambda kv: -kv[1])[:3]) \
            if scores else "not moderated"
        print(f"  {r['id']}: {r['label']} -> {r['predicted']} status={r['status']}  {top}")
    statuses = {}
    for r in results:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    print("Statuses: " + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
    print("\nConfidence cutoff   above  acc_above   below  acc_below")
    for row in summary["cutoffs"]:
        print(f"  {row['cutoff']:<17.2f}{row['above']:>6} {pct(row['accuracy_above']):>10}"
              f"{row['below']:>8} {pct(row['accuracy_below']):>10}")
    if summary["suggested_cutoff"] is None:
        print("Suggested CONFIDENCE_CUTOFF: none, no cutoff catches a wrong prediction without losing right ones")
    else:
        print(f"Suggested CONFIDENCE_CUTOFF: {summary['suggested_cutoff']:.2f} "
              "(most right answers above plus wrong answers caught below)")


def main():
    """Parse arguments, run every row, print the reports and save the results.

    Args (command line):
        --limit N     only the first N rows
        --model ID    override TRIAGE_MODEL for this run
        --file PATH   another golden file
        --workers N   parallel rows (default 4)

    Returns:
        None.

    Raises:
        SystemExit: If the golden set is invalid or copies a few-shot example.

    Side effects: real model calls, stdout, and a results file in eval/results/.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model")
    parser.add_argument("--file", default=str(HERE / "triage_golden.jsonl"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.model:
        os.environ["TRIAGE_MODEL"] = args.model
    rows = load(Path(args.file), args.limit)
    overlaps = few_shot_overlaps(rows, SWEETLIFE_FLORA)
    # Fail fast and before any model call, so a contaminated golden set never
    # produces numbers.
    if overlaps:
        sys.exit("Golden rows match prompt few-shot examples: "
                 + ", ".join(f"{row_id} ~ example {i}" for row_id, i in overlaps))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(predict, rows))
    model = next((r["model"] for r in results if r["model"]), os.environ.get("TRIAGE_MODEL") or llm.DEFAULT_MODEL)
    version = prompt_version(SWEETLIFE_FLORA)
    print(f"Model: {model}   Prompt: {version}")
    summaries = {}
    for split in SPLITS:
        split_results = [r for r in results if r["split"] == split]
        if not split_results:
            print(f"\n=== {split} split: no examples yet ===")
            continue
        summaries[split] = summarize(split_results)
        report(split, split_results, summaries[split])
    costs = [r["cost"] for r in results if r["cost"] is not None]
    latency = sum(r["latency_ms"] for r in results) / len(results)
    tokens = sum(r["tokens"] for r in results)
    print(f"\nAll splits: average latency {latency:.0f} ms   total tokens {tokens}   "
          f"cost {'$%.5f' % sum(costs) if costs else 'n/a'}")
    out = HERE / "results" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"model": model, "prompt_version": version, "splits": summaries,
                               "average_latency_ms": latency, "total_tokens": tokens,
                               "cost": sum(costs) if costs else None, "results": results}, indent=2))
    print(f"Saved {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
