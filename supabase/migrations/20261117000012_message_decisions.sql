-- =============================================================
-- SCRUM-140: record the creator's decision on a DM in "Needs your decision"
-- (docs/plans/scrum-140-moderation-decisions-spec.md)
-- record_message_decision(message_id, decision) runs as the signed-in creator, in one transaction:
--   1. checks the DM belongs to one of her contacts (or the caller is an admin),
--   2. moves it from creator_decision to closed_no_action,
--   3. marks its open checkpoint-1 safety flags creator_reviewed,
--   4. writes one audit_log row (no DM text).
-- Returns 'recorded', or 'already_decided' when the DM is no longer waiting (nothing written).
-- Raises not_authenticated, invalid_decision or not_found.
-- Reuses is_admin() and current_creator_id() from migration 003.
-- Safe to re-run: create or replace.
-- Run in Supabase SQL Editor AFTER 20261102000011_creator_inbox_policies.sql
-- =============================================================

create or replace function public.record_message_decision(p_message_id uuid, p_decision text)
returns text
language plpgsql
volatile
security definer
set search_path = public
as $$
declare
  v_actor  uuid := auth.uid();
  v_status text;
  v_flags  int;
begin
  if v_actor is null then
    raise exception 'not_authenticated' using errcode = '28000';
  end if;

  if p_decision is null or p_decision not in ('replied', 'no_reply_needed') then
    raise exception 'invalid_decision' using errcode = '22023';
  end if;

  -- Lock the row so two clicks or two tabs record one decision.
  select m.status into v_status
  from inbound_messages m
  join ig_followers f on f.id = m.follower_id
  where m.id = p_message_id
    and (f.creator_id = public.current_creator_id() or public.is_admin())
  for update of m;

  if not found then
    raise exception 'not_found' using errcode = 'P0002';
  end if;

  if v_status is distinct from 'creator_decision' then
    return 'already_decided';
  end if;

  update inbound_messages
  set status = 'closed_no_action'
  where id = p_message_id;

  update safety_flags
  set status = 'creator_reviewed', reviewed_by = v_actor
  where target_type = 'message'
    and target_id = p_message_id
    and status = 'open';
  get diagnostics v_flags = row_count;

  insert into audit_log (actor_id, action, entity, entity_id, before_after)
  values (
    v_actor, 'message.decided', 'inbound_message', p_message_id,
    jsonb_build_object(
      'decision', p_decision,
      'before', 'creator_decision',
      'after', 'closed_no_action',
      'flags_reviewed', v_flags
    )
  );

  return 'recorded';
end;
$$;

revoke execute on function public.record_message_decision(uuid, text) from public, anon;
grant execute on function public.record_message_decision(uuid, text) to authenticated;

-- Verification (run as a signed-in creator from the app, or check after one click):
--   select status from inbound_messages where id = '<message id>';                  -- expect closed_no_action
--   select status, reviewed_by from safety_flags where target_id = '<message id>';   -- expect creator_reviewed
--   select action, entity, before_after from audit_log
--    where entity_id = '<message id>' order by created_at desc limit 1;             -- expect message.decided
--   select has_function_privilege('anon', 'public.record_message_decision(uuid, text)', 'execute');  -- expect false
