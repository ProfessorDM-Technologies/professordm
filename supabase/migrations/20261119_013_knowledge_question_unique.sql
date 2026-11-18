-- =============================================================
-- Q&A storage (docs/plans/qa-storage-spec.md, Part C)
-- One saved knowledge entry per answered question. The AI worker's store_qa job checks first;
-- this index is the backstop when SQS delivers the same job twice.
-- Guide chunks and the demo entries have no question_id, so they are not affected.
-- Before running, this must return no rows:
--   select question_id from knowledge_entries
--   where source = 'question' and question_id is not null
--   group by question_id having count(*) > 1;
-- Safe to re-run.
-- Run in Supabase SQL Editor AFTER 20261117_012_message_decisions.sql
-- =============================================================

create unique index if not exists knowledge_entries_question_unique
  on public.knowledge_entries (question_id)
  where source = 'question' and question_id is not null;
