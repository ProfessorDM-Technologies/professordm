-- =============================================================
-- 010: match_knowledge(), hybrid search over knowledge_entries
-- SCRUM-77. Owner: Chinmay (code owner review: Karthik).
-- Spec: docs/plans/kb-draft-implementation-spec.md sections 5 and 14.2.
-- Hybrid search: meaning (cosine distance on the embedding) plus keywords
-- (Postgres full text on title and content), merged with Reciprocal Rank Fusion.
-- `similarity` (1 - cosine distance) is returned for every row and is what gates
-- use; `score` (RRF) only measures rank position and is for ordering.
-- Run AFTER 009 (Karthik): 009 drops the IVFFlat index, so this is a full scan
-- with perfect recall at a few thousand rows.
-- Safe to re-run: create or replace, then revoke and grant.
-- Backend only: the service role calls it; browser roles cannot execute it.
-- =============================================================
begin;

create or replace function public.match_knowledge(
  query_embedding  extensions.vector(1536),
  query_text       text,
  p_creator_id     uuid,
  match_count      int     default 20,
  p_sources        text[]  default null,
  p_published_only boolean default false,
  p_exclude_tags   text[]  default null
)
returns table (
  id uuid, doc_id uuid, question_id uuid, source text, title text, content text,
  tags text[], similarity double precision, score double precision
)
language sql
stable
security invoker
set search_path = public, extensions
as $$
  with base as (
    select e.*
    from public.knowledge_entries e
    where e.creator_id = p_creator_id
      and e.embedding is not null
      and (p_sources is null or e.source = any (p_sources))
      and (not p_published_only or e.published)
      and (p_exclude_tags is null or not (coalesce(e.tags, '{}') && p_exclude_tags))
  ),
  semantic as (
    select b.id, row_number() over (order by b.embedding <=> query_embedding) as rank
    from base b
    order by b.embedding <=> query_embedding
    limit match_count * 2
  ),
  keyword as (
    select b.id,
           row_number() over (order by ts_rank_cd(
             to_tsvector('english', coalesce(b.title, '') || ' ' || coalesce(b.content, '')), q) desc) as rank
    from base b, websearch_to_tsquery('english', coalesce(query_text, '')) q
    where to_tsvector('english', coalesce(b.title, '') || ' ' || coalesce(b.content, '')) @@ q
    order by rank
    limit match_count * 2
  )
  select b.id, b.doc_id, b.question_id, b.source, b.title, b.content, b.tags,
         (1 - (b.embedding <=> query_embedding))::double precision as similarity,
         (coalesce(1.0 / (60 + s.rank), 0) + coalesce(1.0 / (60 + k.rank), 0))::double precision as score
  from base b
  left join semantic s on s.id = b.id
  left join keyword  k on k.id = b.id
  where s.id is not null or k.id is not null
  -- similarity breaks ties, so the order is repeatable when two rows have the same RRF score.
  order by score desc, similarity desc
  limit match_count;
$$;

revoke execute on function public.match_knowledge(extensions.vector, text, uuid, int, text[], boolean, text[]) from public, anon, authenticated;
grant execute on function public.match_knowledge(extensions.vector, text, uuid, int, text[], boolean, text[]) to service_role;

commit;

-- =============================================================
-- Verification (read-only, run after applying):
--   select has_function_privilege('authenticated',
--     'public.match_knowledge(extensions.vector, text, uuid, int, text[], boolean, text[])', 'execute');  -- expect false
--   select has_function_privilege('service_role',
--     'public.match_knowledge(extensions.vector, text, uuid, int, text[], boolean, text[])', 'execute');  -- expect true
--   select count(*) from public.match_knowledge(
--     (select embedding from public.knowledge_entries where embedding is not null limit 1),
--     'watering', (select creator_id from public.knowledge_entries limit 1), 5);                       -- expect 5
-- =============================================================
