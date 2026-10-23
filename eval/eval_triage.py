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
sys.path.insert(0, str(HERE.parent / "services" / "ai_worker"))

import llm
from prompts import CATEGORIES, SWEETLIFE_FLORA, prompt_version
from triage import triage

SPLITS = ("dev", "test")
NEAR_MATCH = 0.9
SHORT = {"expert_question": "expert", "needs_clarification": "clarify", "social": "social",
         "spam_irrelevant": "spam", "safety_concern": "safety", "service_request": "service"}


def load(path, limit):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for row in rows:
        if row.get("split") not in SPLITS or row.get("label") not in CATEGORIES:
            sys.exit(f"{row.get('id')}: split must be dev or test and label one of the 6 categories")
    return rows[:limit] if limit else rows


def _normalize(text):
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def few_shot_overlaps(rows, profile):
    shots = [_normalize(example["text"]) for example in profile["examples"]]
    overlaps = []
    for row in rows:
        for text in [row["text"], *(row.get("recent_messages") or [])]:
            golden = _normalize(text)
            for i, shot in enumerate(shots):
                if golden and SequenceMatcher(None, golden, shot).ratio() >= NEAR_MATCH:
                    overlaps.append((row["id"], i))
    return overlaps


_calls = threading.local()
_openrouter = llm._openrouter


def _recording_openrouter(*args, **kwargs):
    content, meta = _openrouter(*args, **kwargs)
    _calls.meta.append(meta)
    return content, meta


llm._openrouter = _recording_openrouter


def predict(row):
    _calls.meta = []
    started = time.monotonic()
    decision = triage(row["text"], row.get("recent_messages") or [], SWEETLIFE_FLORA)
    risks = [f["detail"] for f in decision["safety_flags"] if f["category"] == "risk_topic"]
    confidence = decision["confidence"]
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
            "latency_ms": int((time.monotonic() - started) * 1000),
            "tokens": sum(m["prompt_tokens"] + m["completion_tokens"] for m in _calls.meta),
            "cost": sum(costs) if costs else None,
            "model": next((m["model"] for m in _calls.meta), None)}


def per_category(results):
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
    return {t: {p: sum(r["label"] == t and r["predicted"] == p for r in results)
                for p in CATEGORIES} for t in CATEGORIES}


def cutoff_table(results):
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
    cutoffs, suggested = cutoff_table(results)
    kinds = [r for r in results if r["service_kind_label"] and r["predicted"] == "service_request"]
    return {"examples": len(results),
            "accuracy": sum(r["label"] == r["predicted"] for r in results) / len(results),
            "service_kind_accuracy": (sum(r["service_kind"] == r["service_kind_label"] for r in kinds)
                                      / len(kinds) if kinds else None),
            "per_category": per_category(results), "confusion": confusion(results),
            "cutoffs": cutoffs, "suggested_cutoff": suggested}


def pct(value):
    return "  n/a" if value is None else f"{value * 100:5.1f}%"


def report(split, results, summary):
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
