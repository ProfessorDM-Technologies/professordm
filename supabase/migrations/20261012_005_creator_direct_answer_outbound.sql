-- =============================================================
-- SCRUM-73: Creator Workspace writes a typed reply to outbound_messages on Send
-- A creator's reply is an existing type = 'answer' row with draft_id = null (no AI draft
-- this milestone). Adds the columns it needs. Every new column is nullable (except
-- created_at, which has a default), so existing rows and the sender's inserts keep working.
-- Adds an INSERT policy so the signed-in creator can queue a 'pending' reply for their own
-- contacts; the sender picks it up from there. The type check is unchanged.
-- Safe to re-run: columns/indexes use if not exists, constraint and policies are dropped first.
-- Run in Supabase SQL Editor AFTER 20261011_004_creator_thread_policies.sql
-- =============================================================

-- =============================================================
-- SECTION 1: Columns
-- =============================================================

alter table outbound_messages
  add column if not exists inbound_message_id uuid references inbound_messages(id),
  add column if not exists follower_id        uuid references ig_followers(id),
  add column if not exists text               text,
  add column if not exists creator_id         uuid references creators(id),
  add column if not exists client_request_id  uuid,
  add column if not exists created_at         timestamptz not null default now();

-- One row per Send press: a double click reuses the same id and is rejected here.
create unique index if not exists outbound_messages_client_request_id_key
  on outbound_messages (client_request_id);

-- Conversation view loads everything sent to one follower.
create index if not exists outbound_messages_follower_id_idx
  on outbound_messages (follower_id);

-- =============================================================
-- SECTION 2: Direct answers must be complete
-- Only applies to type = 'answer' with no draft. Other rows are unaffected.
-- =============================================================

alter table outbound_messages drop constraint if exists outbound_direct_answer_fields;
alter table outbound_messages add constraint outbound_direct_answer_fields check (
  type <> 'answer'
  or draft_id is not null
  or (
    text is not null
    and length(btrim(text)) > 0
    and inbound_message_id is not null
    and follower_id is not null
    and creator_id is not null
    and client_request_id is not null
  )
);

-- =============================================================
-- SECTION 3: RLS
-- Reuses is_admin() and current_creator_id() from migration 003.
-- =============================================================

-- Creator queues a typed answer to one of their own contacts. Delivery fields stay
-- untouched so only the sender can mark a row sent.
drop policy if exists "outbound_messages_insert_creator_direct_answer" on outbound_messages;
create policy "outbound_messages_insert_creator_direct_answer" on outbound_messages
  for insert to authenticated
  with check (
    type = 'answer'
    and draft_id is null
    and status = 'pending'
    and attempts = 0
    and meta_message_id is null
    and creator_id = public.current_creator_id()
    and exists (
      select 1 from inbound_messages m
      join ig_followers f on f.id = m.follower_id
      where m.id = outbound_messages.inbound_message_id
        and f.id = outbound_messages.follower_id
        and f.creator_id = public.current_creator_id()
    )
  );

-- Replaces the 004 policy: also lets the creator read their direct answers (no draft_id).
drop policy if exists "outbound_messages_select_creator_or_admin" on outbound_messages;
create policy "outbound_messages_select_creator_or_admin" on outbound_messages
  for select to authenticated
  using (
    public.is_admin()
    or creator_id = public.current_creator_id()
    or exists (
      select 1 from drafts d
      join questions q on q.id = d.question_id
      where d.id = outbound_messages.draft_id
        and q.creator_id = public.current_creator_id()
    )
  );
