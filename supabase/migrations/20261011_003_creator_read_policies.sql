-- =============================================================
-- SCRUM-56: RLS read policies for the Creator Workspace inbox list
-- A signed-in creator can read their own Instagram followers and the messages they sent.
-- Admins (ProfessorDM staff) can read all. SELECT only: writes go through the api,
-- which uses the service role and bypasses RLS.
-- Safe to re-run: policies are dropped before they are created.
-- Run in Supabase SQL Editor (Project > SQL Editor > New Query)
-- =============================================================

-- =============================================================
-- SECTION 1: Helper functions
-- security definer: they read profiles/creators directly, so policies
-- that call them don't trigger RLS checks inside RLS checks.
-- =============================================================

create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  );
$$;

create or replace function public.current_creator_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select id from creators where profile_id = auth.uid() limit 1;
$$;

revoke execute on function public.is_admin() from public, anon;
revoke execute on function public.current_creator_id() from public, anon;
grant execute on function public.is_admin() to authenticated;
grant execute on function public.current_creator_id() to authenticated;

-- =============================================================
-- SECTION 2: profiles (sign-in role check)
-- Replaces the "read own profile" policy added by hand in the dev project.
-- =============================================================

alter table profiles enable row level security;

drop policy if exists "read own profile" on profiles;
drop policy if exists "profiles_select_own" on profiles;
create policy "profiles_select_own" on profiles
  for select to authenticated
  using (id = auth.uid());

-- =============================================================
-- SECTION 3: Inbox list (followers + inbound messages)
-- =============================================================

alter table ig_followers     enable row level security;
alter table inbound_messages enable row level security;

drop policy if exists "ig_followers_select_creator_or_admin" on ig_followers;
create policy "ig_followers_select_creator_or_admin" on ig_followers
  for select to authenticated
  using (creator_id = public.current_creator_id() or public.is_admin());

drop policy if exists "inbound_messages_select_creator_or_admin" on inbound_messages;
create policy "inbound_messages_select_creator_or_admin" on inbound_messages
  for select to authenticated
  using (
    public.is_admin()
    or exists (
      select 1 from ig_followers f
      where f.id = inbound_messages.follower_id
        and f.creator_id = public.current_creator_id()
    )
  );
