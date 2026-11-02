-- =============================================================
-- Creator Inbox (docs/plans/creator-inbox-spec.md, Part A)
-- 1. A signed-in creator can read the safety flags on their own contacts' messages and on
--    drafts of their own questions. Admins read all.
-- 2. A creator can read their own tags and question tags. Admins read all.
-- 3. Realtime publishes questions and drafts, so new drafts appear in the inbox live.
-- SELECT only. Every write goes through the send API with the service role.
-- Reuses is_admin() and current_creator_id() from migration 003.
-- Safe to re-run: policies are dropped before they are created, publication adds are guarded.
-- Run in Supabase SQL Editor AFTER 20261030_010_match_knowledge.sql
-- =============================================================

alter table safety_flags  enable row level security;
alter table tags          enable row level security;
alter table question_tags enable row level security;

-- Flags on a message (checkpoint 1) via its sender, or on a draft / final answer
-- (checkpoints 2 and 3) via the draft's question.
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
      target_type in ('draft', 'final')
      and exists (
        select 1 from drafts d
        join questions q on q.id = d.question_id
        where d.id = safety_flags.target_id
          and q.creator_id = public.current_creator_id()
      )
    )
  );

drop policy if exists "tags_select_creator_or_admin" on tags;
create policy "tags_select_creator_or_admin" on tags
  for select to authenticated
  using (creator_id = public.current_creator_id() or public.is_admin());

drop policy if exists "question_tags_select_creator_or_admin" on question_tags;
create policy "question_tags_select_creator_or_admin" on question_tags
  for select to authenticated
  using (
    public.is_admin()
    or exists (
      select 1 from questions q
      where q.id = question_tags.question_id
        and q.creator_id = public.current_creator_id()
    )
  );

-- Realtime respects RLS, so a creator only receives changes to rows they can read.
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'questions'
  ) then
    alter publication supabase_realtime add table public.questions;
  end if;

  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'drafts'
  ) then
    alter publication supabase_realtime add table public.drafts;
  end if;
end;
$$;
