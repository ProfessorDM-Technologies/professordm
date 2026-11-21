-- Run in Supabase SQL Editor AFTER 20261119000014_publish_knowledge_entries.sql
--
-- SCRUM-134: remove the browser insert policy on outbound_messages.
-- Since the send API (Oct 2026), every outbound row is written by the backend
-- with the service role, which ignores RLS. No app code inserts into
-- outbound_messages with a user session, so this policy only widens access.
-- The select policy for creators and admins stays.

drop policy if exists outbound_messages_insert_creator_direct_answer on public.outbound_messages;
