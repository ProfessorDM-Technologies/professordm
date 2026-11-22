-- Final answer screen (checkpoint 3, SCRUM-128). See docs/final-answer-screen.md.
-- Checkpoint-3 flags are stored with target_type = 'final' and
-- target_id = outbound_messages.id (the message that was actually sent),
-- so the creator branch for 'final' now joins outbound_messages, not drafts.
-- Checked on staging Nov 22: no rows with target_type = 'final' exist yet.

alter table public.safety_flags
  add column if not exists reviewed_at timestamptz,
  add column if not exists created_at timestamptz not null default now();

drop policy if exists "safety_flags_select_creator_or_admin" on safety_flags;
create policy "safety_flags_select_creator_or_admin" on safety_flags
  for select to authenticated
  using (
    public.is_admin()
    or (
      target_type = 'message'
      and exists (
        select 1 from inbound_messages m
        join ig_followers f on f.id = m.follower_id
        where m.id = safety_flags.target_id
          and f.creator_id = public.current_creator_id()
      )
    )
    or (
      target_type = 'draft'
      and exists (
        select 1 from drafts d
        join questions q on q.id = d.question_id
        where d.id = safety_flags.target_id
          and q.creator_id = public.current_creator_id()
      )
    )
    or (
      target_type = 'final'
      and exists (
        select 1 from outbound_messages o
        where o.id = safety_flags.target_id
          and o.creator_id = public.current_creator_id()
      )
    )
  );

-- Verify after apply:
-- select column_name from information_schema.columns
--   where table_name = 'safety_flags' and column_name in ('reviewed_at', 'created_at');
-- select pg_get_expr(polqual, polrelid) from pg_policy
--   where polname = 'safety_flags_select_creator_or_admin';
