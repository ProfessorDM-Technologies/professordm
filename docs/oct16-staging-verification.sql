-- Run in the staging Supabase SQL Editor after migrations 006 and 007.
-- This returns names and booleans only. It never returns Vault secret values.

select tablename
from pg_publication_tables
where pubname = 'supabase_realtime'
  and schemaname = 'public'
  and tablename in ('inbound_messages', 'outbound_messages')
order by tablename;

select tablename, policyname, roles, cmd, qual
from pg_policies
where schemaname = 'public'
  and tablename in ('inbound_messages', 'outbound_messages')
  and cmd in ('SELECT', 'ALL')
order by tablename, policyname;

select c.relname as tablename, c.relrowsecurity as rls_enabled
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('inbound_messages', 'outbound_messages')
order by c.relname;

select p.proname,
       p.prosecdef as security_definer,
       has_function_privilege('service_role', p.oid, 'EXECUTE') as service_role_execute,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') as authenticated_execute,
       has_function_privilege('anon', p.oid, 'EXECUTE') as anon_execute
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname = 'meta_page_token_for_account';

select count(*) as connected_accounts,
       count(vault_token_id) as vault_linked_accounts
from public.ig_accounts;
