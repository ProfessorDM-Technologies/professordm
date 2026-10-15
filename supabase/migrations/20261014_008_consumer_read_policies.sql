-- =============================================================
-- SCRUM-89: RLS read policies for the Consumer App (Ask Sweetlife Flora)
-- Signed-in users can read published knowledge entries. A consumer can read only their own
-- consumers row. Creators read their own entries and admins read all, so turning RLS on
-- does not hide anything the Creator Workspace needs.
-- Also adds a nullable title to knowledge_entries for the library cards and answer page.
-- SELECT only: writes go through the api, which uses the service role and bypasses RLS.
-- Reuses is_admin() and current_creator_id() from migration 003.
-- Safe to re-run: the column uses if not exists, policies are dropped before they are created.
-- Run in Supabase SQL Editor AFTER 20261011_003_creator_read_policies.sql
-- =============================================================

-- =============================================================
-- SECTION 1: Columns
-- =============================================================

alter table knowledge_entries
  add column if not exists title text;

-- =============================================================
-- SECTION 2: knowledge_entries
-- =============================================================

alter table knowledge_entries enable row level security;

drop policy if exists "knowledge_entries_select_published" on knowledge_entries;
create policy "knowledge_entries_select_published" on knowledge_entries
  for select to authenticated
  using (published = true);

drop policy if exists "knowledge_entries_select_creator_or_admin" on knowledge_entries;
create policy "knowledge_entries_select_creator_or_admin" on knowledge_entries
  for select to authenticated
  using (creator_id = public.current_creator_id() or public.is_admin());

-- =============================================================
-- SECTION 3: consumers (free answers counter)
-- =============================================================

alter table consumers enable row level security;

drop policy if exists "consumers_select_own_or_admin" on consumers;
create policy "consumers_select_own_or_admin" on consumers
  for select to authenticated
  using (profile_id = auth.uid() or public.is_admin());
