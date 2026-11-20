-- =============================================================
-- 009: columns and storage for the AI pipeline (triage, knowledge base, drafts)
-- Owner: Karthik. Spec: docs/plans/kb-draft-implementation-spec.md sections 4 and 14.
-- Run BEFORE 010 (match_knowledge, written by Chinmay).
-- Safe to re-run: every change checks whether it already exists.
-- No data is changed or deleted, except dropping an index that is never useful at this size.
-- =============================================================
begin;

-- -------------------------------------------------------------
-- 1. Triage results (PR #20 request): why, which model, service kind, retry count
-- -------------------------------------------------------------
alter table public.inbound_messages
  add column if not exists reason          text,
  add column if not exists model           text,
  add column if not exists service_kind    text
    check (service_kind in ('platform', 'business', 'out_of_domain')),
  add column if not exists triage_attempts int not null default 0;

-- -------------------------------------------------------------
-- 2. Draft results: coverage, what the guides do not cover, why there is no draft
-- -------------------------------------------------------------
alter table public.drafts
  add column if not exists knowledge_coverage text
    check (knowledge_coverage in ('high', 'partial', 'none')),
  add column if not exists missing_info jsonb not null default '[]'::jsonb,
  add column if not exists reason text
    check (reason in ('no_coverage', 'invalid_output', 'safety_blocked', 'empty_question'));

-- -------------------------------------------------------------
-- 3. Safety flag detail: fixed vocabulary only (for example a profile risk topic). Never DM text.
-- -------------------------------------------------------------
alter table public.safety_flags
  add column if not exists detail text;

-- -------------------------------------------------------------
-- 4. Knowledge entries: drop the IVFFlat index. It was built on an empty table with
--    100 lists, so searches would miss most matches. At a few thousand rows an exact
--    scan is fast and has perfect recall. Revisit (HNSW + iterative scan) past ~20k rows.
-- -------------------------------------------------------------
drop index if exists public.idx_knowledge_entries_embedding;

-- -------------------------------------------------------------
-- 5. Deleting a guide deletes its chunks
-- -------------------------------------------------------------
alter table public.knowledge_entries
  drop constraint if exists knowledge_entries_doc_id_fkey;
alter table public.knowledge_entries
  add constraint knowledge_entries_doc_id_fkey
  foreign key (doc_id) references public.knowledge_docs(id) on delete cascade;

-- -------------------------------------------------------------
-- 6. Storage buckets, private, so every environment gets them (staging created them by hand)
-- -------------------------------------------------------------
insert into storage.buckets (id, name, public)
values
  ('knowledge-docs', 'knowledge-docs', false),
  ('dm-media',       'dm-media',       false),
  ('voice-answers',  'voice-answers',  false)
on conflict (id) do nothing;

commit;

-- =============================================================
-- Verification (read-only, run after applying):
--   select column_name from information_schema.columns
--    where table_schema = 'public'
--      and (table_name, column_name) in (('inbound_messages','reason'), ('inbound_messages','model'),
--          ('inbound_messages','service_kind'), ('inbound_messages','triage_attempts'),
--          ('drafts','knowledge_coverage'), ('drafts','missing_info'), ('drafts','reason'),
--          ('safety_flags','detail'));                                   -- expect 8 rows
--   select indexname from pg_indexes where indexname = 'idx_knowledge_entries_embedding';  -- expect 0 rows
--   select pg_get_constraintdef(oid) from pg_constraint
--    where conname = 'knowledge_entries_doc_id_fkey';                    -- expect ON DELETE CASCADE
--   select id, public from storage.buckets order by id;                  -- expect 3 private buckets
-- =============================================================
