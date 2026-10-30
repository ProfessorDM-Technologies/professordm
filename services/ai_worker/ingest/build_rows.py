# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Turn chunks into database rows with embeddings, ready for load_kb.py.

Ingest step 4 of 5 (spec sections 3.4 and 14.2). Reads private/chunks.jsonl
(chunk.py), the doc.json files (normalize.py, for guide titles) and the 8 demo
Q&A entries in the consumer demo seed, embeds them with llm.embed(), and
writes private/rows.jsonl for load_kb.py.

Contents:
    NAMESPACE            the uuid5 namespace for every id; never changes
    doc_id, entry_id     deterministic ids, so a re-run updates rows instead
                         of duplicating them
    entry_tags           namespaced tags (hpa:, kind:, review:, topic:)
    embedding_input      title + "\\n" + content, for chunks and demo entries
    parse_demo_entries   the 8 demo Q&A entries out of the seed SQL
    build_rows           chunks + docs + demo entries -> rows.jsonl records
    main                 the CLI

rows.jsonl holds three record types, in this order:
    {"table": "knowledge_docs", "op": "upsert", ...}       one per guide
    {"table": "knowledge_entries", "op": "upsert", ...}    one per chunk
    {"table": "knowledge_entries", "op": "set_embedding",
     "id": ..., "embedding": [...]}                         one per demo entry

Usage (from the repo root, with OPENAI_API_KEY in the environment):
    set -a; source .env; set +a
    uv run --python 3.11 services/ai_worker/ingest/build_rows.py --creator-id <uuid>
        [--chunks FILE] [--docs DIR] [--seed FILE] [--out FILE]

Depends on: the standard library, and llm (imported by adding
services/ai_worker to sys.path) for embed().

Never does: touch the database (that is load_kb.py), print guide or demo
text, or write the creator id anywhere except rows.jsonl, which lives in the
git-ignored private/ folder. It prints counts, tokens and cost only.
"""

import argparse
import json
import re
import sys
import uuid
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import llm  # noqa: E402  (needs the sys.path line above)


# Defaults. Inputs and output are under the git-ignored private/; the seed is
# committed team-written demo content, not guide text.
CHUNKS_FILE = HERE / "private" / "chunks.jsonl"
DOCS_DIR = HERE / "private" / "docs"
SEED_FILE = HERE.parents[2] / "supabase" / "seeds" / "20261014_consumer_demo.sql"
OUTPUT_FILE = HERE / "private" / "rows.jsonl"

# The uuid5 namespace for every knowledge_docs and knowledge_entries id this
# script makes. Generated once with uuid4 and committed. It must NEVER change:
# a new namespace gives every guide and chunk a new id, so the next load would
# insert a second copy of the whole knowledge base instead of updating it.
NAMESPACE = uuid.UUID("757cc9e7-09fe-45f6-be7f-bfc56090091d")

# The 8 published demo Q&A entries in the consumer demo seed (spec 14.2, Q9).
# They already exist in knowledge_entries with no embedding; this script only
# adds their vectors (load_kb.py sets them where embedding is still null).
DEMO_IDS = tuple(f"89000000-0000-4000-8000-{n:012d}" for n in range(1, 9))

# One demo entry in the seed's knowledge_entries insert:
#   ('<id>', v_creator_id, 'question', '<title>', $t$<content>$t$, ...
# The title is a SQL single-quoted string ('' is an escaped quote); the
# content is a $t$ dollar-quoted block, taken exactly as written.
DEMO_ENTRY = re.compile(
    r"'(89000000-0000-4000-8000-00000000000[1-8])'\s*,[^',]*,\s*'[a-z_]+'\s*,\s*"
    r"'((?:[^']|'')*)'\s*,\s*"
    r"\$t\$(.*?)\$t\$",
    re.DOTALL)

# OpenAI's price for text-embedding-3-small, US dollars per million tokens
# (October 2026). Only used for the estimate printed at the end.
PRICE_PER_MILLION_TOKENS = 0.02

# Seconds per embeddings request. Longer than the runtime TIMEOUT: a batch of
# 100 chunks takes a few seconds, and ingest is not racing a Lambda deadline.
EMBED_TIMEOUT = 60


def doc_id(hpa_id):
    """Return the knowledge_docs id of a guide.

    Args:
        hpa_id (str): The guide id, for example "HPA-FUND-0001".

    Returns:
        str: uuid5(NAMESPACE, "doc:<hpa_id>"), the same on every run.

    Side effects: none.
    """
    return str(uuid.uuid5(NAMESPACE, f"doc:{hpa_id}"))


def entry_id(chunk):
    """Return the knowledge_entries id of a chunk.

    Args:
        chunk (dict): A chunks.jsonl record (uses hpa_id, kind, chunk_index).

    Returns:
        str: uuid5(NAMESPACE, "<hpa_id>:<chunk_index>"), or
        uuid5(NAMESPACE, "<hpa_id>:card") for the doc card, the same on every
        run.

    Side effects: none.
    """
    suffix = "card" if chunk["kind"] == "card" else chunk["chunk_index"]
    return str(uuid.uuid5(NAMESPACE, f"{chunk['hpa_id']}:{suffix}"))


def entry_tags(chunk):
    """Build a chunk's namespaced tags.

    Namespaced so they never mix with the human display tags on published
    Q&A (spec 3.4), and so retrieval can filter by them (for example
    production excludes "review:pending").

    Args:
        chunk (dict): A chunks.jsonl record (uses hpa_id, kind,
            review_status, care_topics).

    Returns:
        list[str]: ["hpa:<id>", "kind:<kind>", "review:<status>",
        "topic:<t>", ...] in that order, duplicates removed (first kept).

    Side effects: none.
    """
    tags = [f"hpa:{chunk['hpa_id']}", f"kind:{chunk['kind']}", f"review:{chunk['review_status']}"]
    tags += [f"topic:{topic}" for topic in chunk.get("care_topics") or []]
    return list(dict.fromkeys(tags))


def embedding_input(title, content):
    """Return the text that is embedded for one entry.

    Args:
        title (str): The entry title.
        content (str): The entry content.

    Returns:
        str: title + "\\n" + content (spec 3.3 rule 9), the same text chunk.py
        sized as est_tokens.

    Side effects: none.
    """
    return title + "\n" + content


def parse_demo_entries(sql):
    """Read the 8 demo Q&A entries out of the consumer demo seed.

    Args:
        sql (str): The seed file's text.

    Returns:
        list[dict]: [{"id", "title", "content"}] in DEMO_IDS order. The title
        has '' unescaped to '; the content is the $t$ block as written.

    Raises:
        ValueError: Unless exactly the 8 DEMO_IDS are found, once each. The
            message carries counts only.

    Side effects: none.
    """
    found = [{"id": m.group(1), "title": m.group(2).replace("''", "'"), "content": m.group(3)}
             for m in DEMO_ENTRY.finditer(sql)]
    ids = sorted(entry["id"] for entry in found)
    if ids != sorted(DEMO_IDS):
        raise ValueError(f"expected {len(DEMO_IDS)} demo entries, found {len(found)} "
                         f"({len(set(ids))} distinct)")
    return sorted(found, key=lambda entry: entry["id"])


def build_rows(chunks, docs, demo, creator_id):
    """Build every rows.jsonl record, embedding chunks and demo entries.

    Args:
        chunks (list[dict]): chunks.jsonl records.
        docs (list[dict]): doc.json dicts, one per guide (for titles).
        demo (list[dict]): From parse_demo_entries.
        creator_id (str): The creator who owns the guides, already validated.

    Returns:
        tuple[list[dict], dict]: (records, meta). records are the
        knowledge_docs upserts (in docs order), then the knowledge_entries
        upserts (in chunks order), then one set_embedding per demo entry.
        meta is llm.embed's {"model", "tokens", "latency_ms"}.

    Raises:
        ValueError: If a chunk names a guide that has no doc.json, a guide
            has no chunks, or two chunks would get the same id (ids and counts
            in the message, never text).
        llm.LLMError: If embedding fails after its retries.
        RuntimeError: If OPENAI_API_KEY is missing.

    Side effects: llm.embed calls (one request per 100 inputs).
    """
    titles = {doc["hpa_id"]: doc.get("title") or doc["hpa_id"] for doc in docs}
    unknown = sorted({c["hpa_id"] for c in chunks} - set(titles))
    empty = sorted(set(titles) - {c["hpa_id"] for c in chunks})
    if unknown or empty:
        raise ValueError(f"chunks and docs disagree: no doc.json for {unknown}, no chunks for {empty}")
    ids = [entry_id(c) for c in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{len(ids) - len(set(ids))} duplicate chunk ids")
    texts = [embedding_input(c["title"], c["content"]) for c in chunks]
    texts += [embedding_input(entry["title"], entry["content"]) for entry in demo]
    vectors, meta = llm.embed(texts, retry=True, timeout=EMBED_TIMEOUT)
    records = [{"table": "knowledge_docs", "op": "upsert", "id": doc_id(hpa_id), "creator_id": creator_id,
                "title": title, "storage_path": f"{creator_id}/{hpa_id}.docx"}
               for hpa_id, title in titles.items()]
    records += [{"table": "knowledge_entries", "op": "upsert", "id": id_, "creator_id": creator_id,
                 "doc_id": doc_id(c["hpa_id"]), "question_id": None, "source": "doc", "title": c["title"],
                 "content": c["content"], "tags": entry_tags(c), "published": False, "embedding": vector}
                for c, id_, vector in zip(chunks, ids, vectors)]
    records += [{"table": "knowledge_entries", "op": "set_embedding", "id": entry["id"], "embedding": vector}
                for entry, vector in zip(demo, vectors[len(chunks):])]
    return records, meta


def _creator_id(value):
    """Parse --creator-id as a UUID.

    Args:
        value (str): The command-line value.

    Returns:
        str: The canonical lower-case UUID string.

    Raises:
        argparse.ArgumentTypeError: If it is not a UUID. The message never
            repeats the value.

    Side effects: none.
    """
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("must be a UUID") from None


def _read_jsonl(path):
    """Read a JSON Lines file.

    Args:
        path (str | Path): The file.

    Returns:
        list[dict]: One dict per non-empty line.

    Side effects: reads the file.
    """
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def main(argv=None):
    """Build rows.jsonl and print counts, tokens and estimated cost.

    Args (command line):
        --creator-id UUID   required; the creator who owns the guides
        --chunks FILE       chunks JSONL (default private/chunks.jsonl)
        --docs DIR          folder of doc.json files (default private/docs)
        --seed FILE         the demo seed SQL (default the consumer demo seed)
        --out FILE          output JSONL (default private/rows.jsonl)

    Args:
        argv (list[str] | None): Arguments for tests; None reads sys.argv.

    Returns:
        None.

    Raises:
        SystemExit: 2 for a missing or invalid --creator-id; 1 (with a
            message of counts and ids only) for no chunks, no docs, a seed
            without exactly 8 demo entries, chunks that do not match the
            docs, a missing OPENAI_API_KEY or an embeddings failure. Every
            check except the last runs before any paid call.

    Side effects: reads the inputs, calls the embeddings API, writes the
    output file and prints one summary line.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--creator-id", required=True, type=_creator_id)
    parser.add_argument("--chunks", default=str(CHUNKS_FILE))
    parser.add_argument("--docs", default=str(DOCS_DIR))
    parser.add_argument("--seed", default=str(SEED_FILE))
    parser.add_argument("--out", default=str(OUTPUT_FILE))
    args = parser.parse_args(argv)
    chunks = _read_jsonl(args.chunks)
    docs = [json.loads(path.read_text()) for path in sorted(Path(args.docs).glob("*.json"))]
    if not chunks or not docs:
        sys.exit(f"Need chunks and docs: {len(chunks)} chunks in {args.chunks}, {len(docs)} docs in {args.docs}")
    try:
        demo = parse_demo_entries(Path(args.seed).read_text())
        records, meta = build_rows(chunks, docs, demo, args.creator_id)
    except (ValueError, RuntimeError, llm.LLMError) as error:
        sys.exit(f"build_rows failed: {error}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in records))
    cost = meta["tokens"] * PRICE_PER_MILLION_TOKENS / 1_000_000
    print(f"guides={len(docs)} chunks={len(chunks)} demo_entries={len(demo)} records={len(records)} "
          f"model={meta['model']} tokens={meta['tokens']} est_cost_usd={cost:.6f} out={out}")


if __name__ == "__main__":
    main()
