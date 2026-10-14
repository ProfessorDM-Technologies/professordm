-- Backend-only lookup. Never grant this function to browser roles.
-- Requires Supabase Vault's decrypted_secrets view to be installed.
begin;

do $$
begin
  if to_regclass('vault.decrypted_secrets') is null then
    raise exception 'Supabase Vault decrypted_secrets view is unavailable';
  end if;
end;
$$;

create or replace function public.meta_page_token_for_account(p_account_id uuid)
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select secret.decrypted_secret
  from public.ig_accounts as account
  join vault.decrypted_secrets as secret on secret.id = account.vault_token_id
  where account.id = p_account_id
  limit 1;
$$;

revoke execute on function public.meta_page_token_for_account(uuid) from public, anon, authenticated;
grant execute on function public.meta_page_token_for_account(uuid) to service_role;

commit;
