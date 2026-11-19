-- Publish message changes needed by Creator Workspace. Re-runnable in staging.
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'inbound_messages'
  ) then
    alter publication supabase_realtime add table public.inbound_messages;
  end if;

  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'outbound_messages'
  ) then
    alter publication supabase_realtime add table public.outbound_messages;
  end if;
end;
$$;
