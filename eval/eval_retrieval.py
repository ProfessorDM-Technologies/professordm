"""Evaluate knowledge base retrieval at guide level (spec sections 9.1 and 14.7 Q6).

Every row is a question with the guide(s) that answer it. The search returns
ranked chunks; the ranked guides are each hpa_id at its first occurrence
(kb_eval_common.doc_ranking), and a row is a hit at k when any expected guide
is in the top k. The report gives n, hit@3, hit@5 and MRR per origin and
split, then the combined variant + messy line on test against the bar, then
Arun's group, then every miss.

Rows:
    variant  the held-out question variants of every guide, rebuilt at eval
             time with chunk.split_variants (never stored, so they cannot
             drift from what the cards leave out). Id "<hpa_id>:v<i>", where
             i is the variant's index in the guide's full list.
    messy    eval/private/retrieval_golden.jsonl rows from generate_kb_eval.py
    arun     the same file, Arun's independently written queries (SCRUM-91),
             appended by hand; test only

Modes:
    --offline (default)  kb_eval_common.offline_search over ingest's
                         rows.jsonl: cosine only, no database, so it cannot
                         test the keyword half of the hybrid search
    --live               knowledge.search (PR B) against match_knowledge on
                         staging, after the load
    --no-cards           also exclude the doc cards (tag kind:card)

Both modes search with k=20, candidates=50, per_doc=50 and sources=["doc"].
Ranking guides needs the raw chunk order, so the per-doc cap is effectively
off here (the draft uses per_doc=3).

Usage (from the repo root):
    set -a; source .env; set +a
    uv run --python 3.11 python eval/eval_retrieval.py [--offline | --live] [--no-cards]
        [--split dev|test|all] [--origin variant|messy|arun] [--creator-id UUID]

Bar (test, variant + messy): hit@5 >= 90%. Tune chunking on dev only; test is
reported, never tuned on.

Depends on: services/ai_worker (llm for query embeddings, ingest/chunk.py for
split_variants, knowledge for --live), kb_eval_common, OPENAI_API_KEY (and
for --live SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY), and the standard
library. Query embeddings are cached in eval/private/query_embeddings.json.

Never does: print or save query or passage text (output carries ids, scores
and counts), write to the database, or change chunking.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
AI_WORKER = HERE.parent / "services" / "ai_worker"
# ai_worker and the ingest scripts use flat imports, so put both on the path.
sys.path.insert(0, str(AI_WORKER / "ingest"))
sys.path.insert(0, str(AI_WORKER))

import llm  # noqa: E402  (needs the sys.path lines above)
from chunk import split_variants  # noqa: E402
from kb_eval_common import (DOCS_DIR, ROWS_FILE, cached_embed, default_creator, doc_ranking, hit_at,  # noqa: E402
                            load_docs, load_rows, offline_search, reciprocal_rank, split_for)

GOLDEN = HERE / "private" / "retrieval_golden.jsonl"
ORIGINS = ("variant", "messy", "arun")
SPLITS = ("dev", "test")
# Search settings for both modes (A4 prompt): 20 chunks back out of 50
# candidates, guide chunks only, and a per-doc cap high enough to never bind.
SEARCH = {"k": 20, "candidates": 50, "per_doc": 50, "sources": ["doc"]}
# The doc card tag, excluded with --no-cards.
CARD_TAG = "kind:card"
# Bar from spec 9.1, on the test split of variant + messy rows.
BAR_HIT_AT_5 = 0.90
# Guides shown per miss.
MISS_TOP = 3


def variant_rows(docs):
    """Build the held-out variant rows from the guides.

    Uses chunk.split_variants, so the held-out set is exactly what the cards
    leave out. The index in the id is the variant's position in the guide's
    full list, found by walking that list, so this code does not repeat the
    even/odd rule.

    Args:
        docs (list[dict]): kb_eval_common.load_docs() output.

    Returns:
        list[dict]: {"id": "<hpa_id>:v<i>", "split", "query",
        "expected_hpa_ids": [hpa_id], "origin": "variant"}, by guide then
        index.

    Side effects: none.
    """
    rows = []
    for doc in docs:
        variants = doc.get("question_variants") or []
        _, held_out = split_variants(variants)
        pending = iter(held_out)
        want = next(pending, None)
        for i, variant in enumerate(variants):
            if want is not None and variant == want:
                row_id = f"{doc['hpa_id']}:v{i}"
                rows.append({"id": row_id, "split": split_for(row_id), "query": variant,
                             "expected_hpa_ids": [doc["hpa_id"]], "origin": "variant"})
                want = next(pending, None)
    return rows


def golden_rows(path, guide_ids):
    """Read and validate the messy and Arun rows, if the file exists.

    Arun's rows are test only: a missing split becomes "test" and "dev" is
    rejected, so his queries are never tuned on.

    Args:
        path (Path): retrieval_golden.jsonl.
        guide_ids (set[str]): Every hpa_id in the guides.

    Returns:
        list[dict]: {"id", "split", "query", "expected_hpa_ids", "origin",
        ...}, in file order; [] when the file does not exist yet.

    Raises:
        SystemExit: On a row with a missing id or query, an origin other
            than messy or arun, a bad split, or expected ids that are empty
            or not guides.

    Side effects: reads the file.
    """
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for row in rows:
        if row.get("origin") == "arun":
            row.setdefault("split", "test")
        ids = row.get("expected_hpa_ids")
        if (not row.get("id") or not (row.get("query") or "").strip() or row.get("origin") not in ("messy", "arun")
                or row.get("split") not in SPLITS or (row["origin"] == "arun" and row["split"] != "test")
                or not isinstance(ids, list) or not ids or any(i not in guide_ids for i in ids)):
            sys.exit(f"{row.get('id')}: needs id, query, origin messy|arun, split dev|test (arun: test only) "
                     "and expected_hpa_ids naming known guides")
    return rows


def live_search():
    """Import knowledge.search for --live, or exit with a clear message.

    knowledge.py arrives in PR B, so it is imported only when asked for, and
    this script never carries a second RPC client.

    Returns:
        callable: knowledge.search.

    Raises:
        SystemExit: If services/ai_worker/knowledge.py does not exist yet.

    Side effects: imports the module.
    """
    try:
        import knowledge
    except ModuleNotFoundError as error:
        if error.name != "knowledge":
            raise
        sys.exit("--live needs services/ai_worker/knowledge.py (PR B); use --offline until it lands")
    return knowledge.search


def score(row, results):
    """Score one row's search results at guide level.

    Args:
        row (dict): The eval row.
        results (list[dict]): Search results, best first.

    Returns:
        dict: {"id", "split", "origin", "expected", "ranking" (the first 10
        guides), "hit3", "hit5", "rr", "best_similarity"}. No query text.

    Side effects: none.
    """
    ranking = doc_ranking(results)
    expected = row["expected_hpa_ids"]
    return {"id": row["id"], "split": row["split"], "origin": row["origin"], "expected": expected,
            "ranking": ranking[:10], "hit3": hit_at(ranking, expected, 3), "hit5": hit_at(ranking, expected, 5),
            "rr": reciprocal_rank(ranking, expected),
            "best_similarity": max((r["similarity"] for r in results), default=0.0)}


def metrics(scored):
    """Summarize a group of scored rows.

    Args:
        scored (list[dict]): score() outputs.

    Returns:
        dict: {"n", "hit3", "hit5", "mrr"}; the rates are None for an empty
        group.

    Side effects: none.
    """
    n = len(scored)
    if not n:
        return {"n": 0, "hit3": None, "hit5": None, "mrr": None}
    return {"n": n, "hit3": sum(r["hit3"] for r in scored) / n, "hit5": sum(r["hit5"] for r in scored) / n,
            "mrr": sum(r["rr"] for r in scored) / n}


def pct(value):
    """Format a fraction as a percentage for the report.

    Args:
        value (float | None): A fraction from 0 to 1.

    Returns:
        str: For example " 97.7%", or "   n/a" for None.

    Side effects: none.
    """
    return "   n/a" if value is None else f"{value * 100:5.1f}%"


def _line(label, split, m):
    """Format one report table line.

    Args:
        label (str): The origin or group name.
        split (str): The split name.
        m (dict): metrics() output.

    Returns:
        str: The aligned line.

    Side effects: none.
    """
    mrr = "  n/a" if m["mrr"] is None else f"{m['mrr']:.3f}"
    return f"  {label:<15}{split:<6}{m['n']:>5} {pct(m['hit3']):>8} {pct(m['hit5']):>8} {mrr:>7}"


def report(scored, mode):
    """Print the tables and the misses, and return the numbers to save.

    Args:
        scored (list[dict]): score() outputs for every row run.
        mode (str): A label such as "offline" or "offline, no cards".

    Returns:
        dict: {"groups": {"<origin>/<split>": metrics}, "combined_test":
        metrics, "bar_hit5": float, "passes_bar": bool | None, "arun_test":
        metrics}.

    Side effects: prints to stdout (ids and numbers only).
    """
    print(f"\n=== Retrieval, {mode}: {len(scored)} rows ===")
    print(f"  {'origin':<15}{'split':<6}{'n':>5} {'hit@3':>8} {'hit@5':>8} {'MRR':>7}")
    groups = {}
    for origin in ORIGINS:
        for split in SPLITS:
            rows = [r for r in scored if r["origin"] == origin and r["split"] == split]
            if rows:
                groups[f"{origin}/{split}"] = metrics(rows)
                print(_line(origin, split, groups[f"{origin}/{split}"]))
    combined = metrics([r for r in scored if r["origin"] in ("variant", "messy") and r["split"] == "test"])
    passes = None if combined["hit5"] is None else combined["hit5"] >= BAR_HIT_AT_5
    print(_line("variant+messy", "test", combined)
          + ("" if passes is None else f"   bar hit@5 >= {BAR_HIT_AT_5:.0%}: {'PASS' if passes else 'FAIL'}"))
    arun = metrics([r for r in scored if r["origin"] == "arun"])
    print(_line("arun", "test", arun) if arun["n"] else "  arun           test  none yet (SCRUM-91)")
    misses = [r for r in scored if not r["hit5"]]
    print(f"\nMisses at 5 ({len(misses)}): id, expected -> top {MISS_TOP} predicted")
    for r in misses:
        print(f"  {r['id']} [{r['split']}]: {', '.join(r['expected'])} -> {', '.join(r['ranking'][:MISS_TOP]) or 'none'}")
    near = [r for r in scored if r["hit5"] and not r["hit3"]]
    if near:
        print(f"Hit at 5 but not at 3 ({len(near)}): " + ", ".join(r["id"] for r in near))
    return {"groups": groups, "combined_test": combined, "bar_hit5": BAR_HIT_AT_5, "passes_bar": passes,
            "arun_test": arun}


def main():
    """Parse arguments, build the rows, search every row, report and save.

    Args (command line):
        --offline | --live   search mode (default offline)
        --no-cards           exclude the doc cards
        --split S            dev | test | all (default all)
        --origin O           only variant, messy or arun rows
        --creator-id UUID    default: the single creator in rows.jsonl
        --rows PATH          rows.jsonl: the chunks for --offline, and the
                             default creator in both modes (default
                             ingest's private/)
        --golden PATH        the messy and Arun rows (default eval/private/)

    Returns:
        None.

    Raises:
        SystemExit: If the inputs are missing or invalid, or --live is asked
            for before knowledge.py exists.

    Side effects: embedding calls for uncached queries, stdout, the query
    cache, and a results file in eval/results/ (git-ignored).
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--no-cards", action="store_true")
    parser.add_argument("--split", choices=[*SPLITS, "all"], default="all")
    parser.add_argument("--origin", choices=ORIGINS)
    parser.add_argument("--creator-id")
    parser.add_argument("--rows", default=str(ROWS_FILE))
    parser.add_argument("--golden", default=str(GOLDEN))
    args = parser.parse_args()
    docs = load_docs(DOCS_DIR)
    rows = variant_rows(docs) + golden_rows(Path(args.golden), {doc["hpa_id"] for doc in docs})
    rows = [r for r in rows if (args.split == "all" or r["split"] == args.split)
            and (not args.origin or r["origin"] == args.origin)]
    if not rows:
        sys.exit("No rows match --split and --origin")
    embed = cached_embed(llm.embed, model=llm.EMBED_MODEL)
    settings = {**SEARCH, "exclude_tags": [CARD_TAG] if args.no_cards else []}
    # rows.jsonl names the creator the load used, so it is the default in
    # both modes; --live reads nothing else from it.
    entries = load_rows(Path(args.rows))
    creator_id = args.creator_id or default_creator(entries)
    if args.live:
        search = live_search()
        searched = "match_knowledge (staging)"
    else:
        searched = f"{len(entries)} chunks in {Path(args.rows).name}"

        def search(query, creator, **kwargs):
            """offline_search over the loaded rows, with knowledge.search's signature."""
            return offline_search(query, creator, rows=entries, **kwargs)

    # Embed every uncached query in one batched call before searching, so the
    # searches below are all cache hits.
    embed([row["query"] for row in rows])
    scored = [score(row, search(row["query"], creator_id, embed=embed, **settings)) for row in rows]
    label = ("live" if args.live else "offline (vector only)") + (", no cards" if args.no_cards else "")
    print(f"Mode: {label}   Searched: {searched}   Embeddings: {embed.stats['misses']} new, "
          f"{embed.stats['hits'] - len(rows)} cached")
    summary = report(scored, label)
    out = HERE / "results" / f"retrieval-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"mode": "live" if args.live else "offline", "no_cards": args.no_cards,
                               "split": args.split, "origin": args.origin, "search": settings,
                               "embed_model": llm.EMBED_MODEL, **summary, "results": scored}, indent=2))
    print(f"Saved {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
