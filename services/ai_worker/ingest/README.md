# Knowledge base ingest

Laptop-only scripts that turn the Academy `.docx` guides into `knowledge_docs` and `knowledge_entries` rows on Supabase (spec: `docs/plans/kb-draft-implementation-spec.md`, sections 3 and 14).

```
parse.py       .docx -> body, references, metadata (python-docx, reading only)
normalize.py   private/input/*.docx -> private/docs/<hpa_id>.json
chunk.py       private/docs -> private/chunks.jsonl
build_rows.py  chunks + docs + demo seed -> private/rows.jsonl (with embeddings)
load_kb.py     private/rows.jsonl -> Supabase (upsert, stale delete, --dry-run)
```

> **Never commit anything under `private/`.** It holds the guides, their parsed text, chunks, embeddings and the creator id. Only the scripts and this README are committed. `private/` is git-ignored here; still run `git status` before every commit.

Run every command from the repo root.

## For Chinmay: building the rows

1. Copy the guide `.docx` files into `services/ai_worker/ingest/private/input/`.
2. Normalize:
   `uv run services/ai_worker/ingest/normalize.py`
3. Chunk, then read 3 guides end to end by eye:
   `uv run --python 3.11 services/ai_worker/ingest/chunk.py`
   `uv run --python 3.11 services/ai_worker/ingest/chunk.py --show <HPA-ID>`
4. Build the rows (needs `OPENAI_API_KEY`; costs well under $0.01 for about 400 inputs):
   ```
   set -a; source .env; set +a
   uv run --python 3.11 services/ai_worker/ingest/build_rows.py --creator-id <creator uuid>
   ```
   It prints counts, tokens and the estimated cost, and writes `private/rows.jsonl`.
5. Hand `rows.jsonl` to Karthik privately (never through the repo, an issue or a public channel).

## For Karthik: loading staging

1. Apply migration 009, then 010.
2. Set the environment variables (never put them in a file in the repo):
   ```
   export SUPABASE_URL=<staging project URL>
   export SUPABASE_SERVICE_ROLE_KEY=<staging service-role key>
   ```
3. Dry run, and review it. It only reads: rows to upsert and stale chunk ids per guide, how many demo Q&A embeddings would be set, and any `knowledge_docs` of this creator that are not in the file (reported, never deleted).
   `uv run --python 3.11 services/ai_worker/ingest/load_kb.py --rows <path>/rows.jsonl --dry-run`
4. Real run (same command without `--dry-run`). It upserts the docs, upserts the entries in batches of 50, deletes each guide's stale chunks, then sets the demo embeddings only where they are still null. It exits non-zero naming the step and HTTP status on any error; re-running is safe.
5. Check in the Table Editor:
   - the `knowledge_entries` count with `source = 'doc'` matches the printed `entries`;
   - every `source = 'doc'` row has `published = false`;
   - the 8 demo rows (`89000000-0000-4000-8000-00000000000N`) now have an embedding.
6. Run the dry run again: it should show `stale=0` for every guide and `demo_would_update=0`.
7. Upload the original `.docx` files to the private `knowledge-docs` bucket as `<creator_id>/<hpa_id>.docx` (the `storage_path` on each `knowledge_docs` row).
