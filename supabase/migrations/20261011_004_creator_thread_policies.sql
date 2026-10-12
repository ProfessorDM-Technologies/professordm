-- =============================================================
-- SCRUM-56: RLS read policies for the Creator Workspace conversation view
-- Lets a signed-in creator read the clarifications, questions, approved drafts and
-- outbound sends that belong to their own Instagram contacts. Admins read all.
-- SELECT only. Reuses is_admin() and current_creator_id() from migration 003.
-- Safe to re-run: policies are dropped before they are created.
-- Run in Supabase SQL Editor AFTER 20261011_003_creator_read_policies.sql
-- =============================================================

alter table clarification_rounds enable row level security;
alter table questions            enable row level security;
alter table drafts               enable row level security;
alter table outbound_messages    enable row level security;

-- Clarification prompt + reply, via the inbound message's sender
drop policy if exists "clarification_rounds_select_creator_or_admin" on clarification_rounds;
create policy "clarification_rounds_select_creator_or_admin" on clarification_rounds
  for select to authenticated
  using (
    public.is_admin()
    or exists (
      select 1 from inbound_messages m
      join ig_followers f on f.id = m.follower_id
      where m.id = clarification_rounds.message_id
        and f.creator_id = public.current_creator_id()
    )
  );

-- Questions asked of this creator
drop policy if exists "questions_select_creator_or_admin" on questions;
create policy "questions_select_creator_or_admin" on questions
  for select to authenticated
  using (creator_id = public.current_creator_id() or public.is_admin());

-- Drafts (holds the answer text that was sent), via the question
drop policy if exists "drafts_select_creator_or_admin" on drafts;
create policy "drafts_select_creator_or_admin" on drafts
  for select to authenticated
  using (
    public.is_admin()
    or exists (
      select 1 from questions q
      where q.id = drafts.question_id
        and q.creator_id = public.current_creator_id()
    )
  );

-- Outbound sends (type + delivery status), via draft -> question
drop policy if exists "outbound_messages_select_creator_or_admin" on outbound_messages;
create policy "outbound_messages_select_creator_or_admin" on outbound_messages
  for select to authenticated
  using (
    public.is_admin()
    or exists (
      select 1 from drafts d
      join questions q on q.id = d.question_id
      where d.id = outbound_messages.draft_id
        and q.creator_id = public.current_creator_id()
    )
  );
