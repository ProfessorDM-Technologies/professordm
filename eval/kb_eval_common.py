"""Shared helpers for the knowledge base evals (retrieval now, drafts in PR B).

Spec sections 6.3, 9 and 14.7 (Q5 to Q7). Both evals score retrieval at guide
level and split rows 30% dev / 70% test by a hash of the row id, so those
rules live here once.

Contents:
    load_docs          ingest/private/docs/*.json -> doc dicts
    load_rows          rows.jsonl -> the knowledge_entries upsert rows
    default_creator    the single creator id in those rows
    cached_embed       wraps an embed function with the query embedding cache
    offline_search     knowledge.search (spec 6.3) without SQL: vector only
    split_for          row id -> "dev" or "test"
    doc_ranking        search results -> hpa ids in first-seen order
    hit_at, reciprocal_rank   the doc-level metrics

Depends on: the standard library only. Nothing here calls a model itself;
offline_search and cached_embed take the embed function as an argument
(llm.embed in the eval scripts, a fake in tests).

Never does: touch the database, or print or log guide, query or passage text.
The query cache stores sha256 hashes of query text, never the text itself,
and lives in the git-ignored eval/private/.
"""

import hashlib
import json
import math
import operator
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
# The normalized guides (normalize.py) and the embedded rows (build_rows.py),
# both under the ingest scripts' git-ignored private/.
DOCS_DIR = REPO / "services" / "ai_worker" / "ingest" / "private" / "docs"
ROWS_FILE = REPO / "services" / "ai_worker" / "ingest" / "private" / "rows.jsonl"
# Query vectors already paid for, so reruns of an eval embed only new queries.
QUERY_CACHE = HERE / "private" / "query_embeddings.json"

# Rows whose hash bucket (0 to 9) is below this go to dev: 3 of 10 buckets,
# the 30% dev / 70% test split of spec 14.4 Q18.
DEV_BUCKETS = 3

# Tag prefix that carries a chunk's guide id (build_rows.entry_tags), the same
# one knowledge.search reads hpa_id from.
HPA_TAG = "hpa:"


def load_docs(folder=DOCS_DIR):
    """Read every normalized guide.

    Args:
        folder (Path): The folder of doc.json files (normalize.py output).

    Returns:
        list[dict]: The doc dicts, sorted by hpa_id.

    Raises:
        SystemExit: If the folder holds no doc.json files (ingest has not
            run on this machine).

    Side effects: reads the files.
    """
    docs = [json.loads(path.read_text()) for path in sorted(Path(folder).glob("*.json"))]
    if not docs:
        raise SystemExit(f"No doc.json files in {folder}; run the ingest steps first")
    return sorted(docs, key=lambda doc: doc["hpa_id"])


def load_rows(path=ROWS_FILE):
    """Read the knowledge_entries upsert rows (the doc chunks with embeddings).

    The knowledge_docs rows and the demo Q&A "set_embedding" records are
    skipped: the first have no vector, the second have no text or tags, and
    the retrieval eval searches guide chunks only (sources=["doc"]).

    Args:
        path (Path): rows.jsonl from build_rows.py.

    Returns:
        list[dict]: Rows shaped like knowledge_entries: {"id", "creator_id",
        "doc_id", "question_id", "source", "title", "content", "tags",
        "published", "embedding", ...}, in file order.

    Raises:
        SystemExit: If the file is missing.

    Side effects: reads the file.
    """
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"{path} not found; run build_rows.py first")
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("table") == "knowledge_entries" and record.get("op") == "upsert":
            rows.append(record)
    return rows


def default_creator(rows):
    """Return the creator id when the rows belong to exactly one creator.

    Args:
        rows (list[dict]): load_rows() output.

    Returns:
        str: The creator id.

    Raises:
        SystemExit: If there are no rows or more than one creator (then
            --creator-id must be given).

    Side effects: none.
    """
    creators = {row["creator_id"] for row in rows}
    if len(creators) != 1:
        raise SystemExit(f"rows.jsonl has {len(creators)} creators; pass --creator-id")
    return creators.pop()


def _query_key(text):
    """Hash a query for the cache, so the cache file never holds query text.

    Args:
        text (str): The query.

    Returns:
        str: The sha256 hex digest of the UTF-8 text.

    Side effects: none.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cached_embed(embed, path=QUERY_CACHE, model=None):
    """Wrap an embed function so each query text is embedded only once.

    The cache is a JSON file {"model": str, "vectors": {sha256: vector}}. A
    cache written for a different model is ignored (and overwritten on the
    next save), because vectors from two models cannot be compared.

    Args:
        embed (callable): Same contract as llm.embed: texts -> (vectors, meta).
        path (Path): The cache file.
        model (str | None): The embedding model id the cache belongs to
            (llm.EMBED_MODEL). None skips the model check (tests).

    Returns:
        callable: (texts, **options) -> (vectors, meta), the same contract as
        embed. options (knowledge.search passes retry=False) are handed to
        embed unchanged on a miss. Cached texts make no call; meta then
        reports 0 tokens. The wrapper also has a .stats dict {"hits": int,
        "misses": int}.

    Side effects: reads the cache file once; every call with a miss calls
    embed for the missing texts and rewrites the file.
    """
    path = Path(path)
    vectors = {}
    if path.exists():
        saved = json.loads(path.read_text())
        if model is None or saved.get("model") == model:
            vectors = saved.get("vectors", {})

    def wrapped(texts, **options):
        """Embed only the texts that are not cached yet; see cached_embed."""
        texts = list(texts)
        keys = [_query_key(text) for text in texts]
        missing = [i for i, key in enumerate(keys) if key not in vectors]
        meta = {"model": model, "tokens": 0, "latency_ms": 0}
        if missing:
            fresh, meta = embed([texts[i] for i in missing], **options)
            for i, vector in zip(missing, fresh):
                vectors[keys[i]] = vector
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps({"model": model, "vectors": vectors}))
        wrapped.stats["hits"] += len(texts) - len(missing)
        wrapped.stats["misses"] += len(missing)
        return [vectors[key] for key in keys], meta

    wrapped.stats = {"hits": 0, "misses": 0}
    return wrapped


def _cosine(a, b, norm_b):
    """Cosine similarity, the same number as SQL's 1 - (a <=> b).

    Args:
        a (list[float]): A stored embedding.
        b (list[float]): The query embedding.
        norm_b (float): The length of b, computed once per query.

    Returns:
        float: The similarity, or 0.0 when either vector has zero length.

    Side effects: none.
    """
    norm_a = math.hypot(*a)
    if not norm_a or not norm_b:
        return 0.0
    return sum(map(operator.mul, a, b)) / (norm_a * norm_b)


def _hpa_id(tags):
    """Read the guide id from a row's tags, as knowledge.search does.

    Args:
        tags (list[str] | None): The row's tags.

    Returns:
        str | None: The value of the first "hpa:" tag, or None.

    Side effects: none.
    """
    return next((tag[len(HPA_TAG):] for tag in tags or [] if tag.startswith(HPA_TAG)), None)


def offline_search(query_text, creator_id, *, k=8, candidates=20, per_doc=3, sources=None,
                   exclude_tags=None, rows, embed):
    """Search the in-memory rows the way knowledge.search searches the database.

    Mirrors match_knowledge (migration 010) plus knowledge.search's per-doc
    cap (spec 6.3), without SQL: filter by creator, embedding present,
    source and excluded tags (a row with null tags is never excluded), rank
    by cosine similarity, keep `candidates`, apply the per-doc cap (a row
    with a null doc_id is its own group) in rank order, then keep the top k.

    It is vector only, so it cannot test the keyword half of the hybrid
    search; score is set to similarity. Ties are broken by row id so a run
    is repeatable.

    Args:
        query_text (str): The search text.
        creator_id (str): Only this creator's rows are searched.
        k (int): Results returned.
        candidates (int): Rows taken from the ranking before the per-doc cap
            (match_count in the RPC).
        per_doc (int): Most rows kept per doc_id.
        sources (list[str] | None): Keep only these sources; None keeps all.
        exclude_tags (list[str] | None): Drop rows carrying any of these tags.
        rows (list[dict]): load_rows() output.
        embed (callable): texts -> (vectors, meta), like llm.embed; called
            once with [query_text].

    Returns:
        list[dict]: At most k results, best first, the same shape as
        knowledge.search: {"entry_id", "doc_id", "hpa_id", "source", "title",
        "content", "similarity", "score"}.

    Raises:
        Whatever embed raises (llm.LLMError for an API failure).

    Side effects: one embed call (none on a cache hit with cached_embed).
    """
    vectors, _ = embed([query_text])
    query = vectors[0]
    norm = math.hypot(*query)
    excluded = set(exclude_tags or [])
    scored = []
    for row in rows:
        if row.get("creator_id") != creator_id or not row.get("embedding"):
            continue
        if sources is not None and row.get("source") not in sources:
            continue
        if excluded & set(row.get("tags") or []):
            continue
        scored.append((_cosine(row["embedding"], query, norm), row))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    results, per_group = [], {}
    for similarity, row in scored[:candidates]:
        # A null doc_id (a Q&A entry) is its own group, keyed by the entry id.
        group = row.get("doc_id") or ("entry", row["id"])
        if per_group.get(group, 0) >= per_doc:
            continue
        per_group[group] = per_group.get(group, 0) + 1
        results.append({"entry_id": row["id"], "doc_id": row.get("doc_id"), "hpa_id": _hpa_id(row.get("tags")),
                        "source": row.get("source"), "title": row.get("title"), "content": row.get("content"),
                        "similarity": similarity, "score": similarity})
        if len(results) == k:
            break
    return results


def split_for(row_id):
    """Assign a row to dev or test by a hash of its id (spec 14.4 Q18).

    Deterministic: the same id always lands in the same split, on every
    machine, so nobody can move a row between splits by rerunning.

    Args:
        row_id (str): The row id, for example "HPA-FUND-0001:v3" or "ret-004".

    Returns:
        str: "dev" when the sha256 of the id, as an integer, mod 10 is below
        DEV_BUCKETS, otherwise "test".

    Side effects: none.
    """
    return "dev" if int(hashlib.sha256(row_id.encode("utf-8")).hexdigest(), 16) % 10 < DEV_BUCKETS else "test"


def doc_ranking(results):
    """Turn ranked chunks into ranked guides (spec 14.7 Q6).

    Args:
        results (list[dict]): Search results, best first.

    Returns:
        list[str]: Each hpa_id at its first occurrence, in order. Results
        without an hpa_id (demo Q&A) are skipped.

    Side effects: none.
    """
    ranking = []
    for result in results:
        if result.get("hpa_id") and result["hpa_id"] not in ranking:
            ranking.append(result["hpa_id"])
    return ranking


def hit_at(ranking, expected, k):
    """Check whether any expected guide is in the top k.

    Args:
        ranking (list[str]): doc_ranking() output.
        expected (list[str]): The row's expected_hpa_ids.
        k (int): The cutoff.

    Returns:
        bool: True when at least one expected id is in ranking[:k].

    Side effects: none.
    """
    return any(hpa_id in expected for hpa_id in ranking[:k])


def reciprocal_rank(ranking, expected):
    """Reciprocal rank of the first expected guide.

    Args:
        ranking (list[str]): doc_ranking() output.
        expected (list[str]): The row's expected_hpa_ids.

    Returns:
        float: 1 / position (1-based) of the first ranked id that is
        expected, or 0.0 when none is ranked.

    Side effects: none.
    """
    return next((1 / position for position, hpa_id in enumerate(ranking, 1) if hpa_id in expected), 0.0)
