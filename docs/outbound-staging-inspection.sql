-- Read-only catalog inspection for staging project lejzezabvfhnfovkyxsx.
-- Run in Supabase SQL Editor. Returns one JSON row, with no row data or secrets.
select jsonb_build_object(
  'outbound_columns', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'name', column_name, 'type', udt_name, 'nullable', is_nullable,
      'default', column_default
    ) order by ordinal_position), '[]'::jsonb)
    from information_schema.columns
    where table_schema = 'public' and table_name = 'outbound_messages'
  ),
  'outbound_constraints', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'name', conname, 'type', contype,
      'definition', pg_get_constraintdef(oid)
    ) order by conname), '[]'::jsonb)
    from pg_constraint
    where conrelid = 'public.outbound_messages'::regclass
  ),
  'outbound_indexes', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'name', indexname, 'definition', indexdef
    ) order by indexname), '[]'::jsonb)
    from pg_indexes
    where schemaname = 'public' and tablename = 'outbound_messages'
  ),
  'rls', (
    select jsonb_agg(jsonb_build_object(
      'table', relname, 'enabled', relrowsecurity, 'forced', relforcerowsecurity
    ) order by relname)
    from pg_class
    where oid in ('public.outbound_messages'::regclass, 'public.inbound_messages'::regclass)
  ),
  'policies', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'table', tablename, 'name', policyname, 'roles', roles,
      'command', cmd, 'using', qual, 'with_check', with_check
    ) order by tablename, policyname), '[]'::jsonb)
    from pg_policies
    where schemaname = 'public'
      and tablename in ('outbound_messages', 'inbound_messages')
  ),
  'realtime', (
    select jsonb_agg(jsonb_build_object(
      'table', t.table_name, 'published', exists (
        select 1 from pg_publication p
        where p.pubname = 'supabase_realtime'
          and (p.puballtables or exists (
            select 1 from pg_publication_rel r
            where r.prpubid = p.oid and r.prrelid = to_regclass('public.' || t.table_name)
          ))
      )
    ))
    from (values ('inbound_messages'), ('outbound_messages')) as t(table_name)
  ),
  'vault_rpc', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'name', p.proname, 'arguments', pg_get_function_identity_arguments(p.oid),
      'security_definer', p.prosecdef,
      'service_role_execute', has_function_privilege('service_role', p.oid, 'EXECUTE'),
      'authenticated_execute', has_function_privilege('authenticated', p.oid, 'EXECUTE'),
      'anon_execute', has_function_privilege('anon', p.oid, 'EXECUTE')
    )), '[]'::jsonb)
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname = 'meta_page_token_for_account'
  )
) as outbound_staging_catalog;
