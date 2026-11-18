-- =============================================================
-- SCRUM-143: the creator publishes or unpublishes a saved answer entry
-- (docs/plans/scrum-143-publish-answers-spec.md)
-- set_knowledge_entry_published(entry_id, published) runs as the signed-in creator, in one transaction:
--   1. checks the entry is an answer entry (source = 'question') and hers (or the caller is an admin),
--   2. sets published,
--   3. writes one audit_log row (no answer text).
-- Returns 'updated', or 'unchanged' when the entry is already in that state (nothing written).
-- Raises not_authenticated (28000), invalid_value (22023) or not_found (P0002), as migration 012 does.
-- Guide chunks (source = 'doc') and manual facts are out of reach of this function.
-- Reuses is_admin() and current_creator_id() from migration 003.
-- Safe to re-run: create or replace.
-- Run in Supabase SQL Editor AFTER 20261119_013_knowledge_question_unique.sql
-- =============================================================

create or replace function public.set_knowledge_entry_published(p_entry_id uuid, p_published boolean)
returns text
language plpgsql
volatile
security definer
set search_path = public
as $$
declare
  v_actor       uuid := auth.uid();
  v_published   boolean;
  v_question_id uuid;
begin
  if v_actor is null then
    raise exception 'not_authenticated' using errcode = '28000';
  end if;

  if p_published is null then
    raise exception 'invalid_value' using errcode = '22023';
  end if;

  -- Lock the row so two clicks or two tabs can't interleave.
  select e.published, e.question_id into v_published, v_question_id
  from knowledge_entries e
  where e.id = p_entry_id
    and e.source = 'question'
    and (e.creator_id = public.current_creator_id() or public.is_admin())
  for update;

  if not found then
    raise exception 'not_found' using errcode = 'P0002';
  end if;

  if v_published = p_published then
    return 'unchanged';
  end if;

  update knowledge_entries
  set published = p_published
  where id = p_entry_id;

  insert into audit_log (actor_id, action, entity, entity_id, before_after)
  values (
    v_actor,
    case when p_published then 'knowledge.published' else 'knowledge.unpublished' end,
    'knowledge_entry',
    p_entry_id,
    jsonb_build_object('before', v_published, 'after', p_published, 'question_id', v_question_id)
  );

  return 'updated';
end;
$$;

revoke execute on function public.set_knowledge_entry_published(uuid, boolean) from public, anon;
grant execute on function public.set_knowledge_entry_published(uuid, boolean) to authenticated;

-- Test rows for local or staging checks (optional; Arun's "TEST private QA" row works too).
-- Use your creator id: select id from creators where profile_id = '<your auth user id>';
--   insert into knowledge_entries (creator_id, source, title, content, tags, published)
--   values ('<creator id>', 'question', 'TEST How often should I water a calathea?',
--           'Keep the soil lightly moist, never soggy.', array['calathea', 'watering'], false);

-- Verification (after one click in /knowledge):
--   select published from knowledge_entries where id = '<entry id>';                -- flipped
--   select action, before_after from audit_log
--    where entity_id = '<entry id>' order by created_at desc limit 1;               -- knowledge.published / unpublished
--   select has_function_privilege('anon', 'public.set_knowledge_entry_published(uuid, boolean)', 'execute');  -- expect false
