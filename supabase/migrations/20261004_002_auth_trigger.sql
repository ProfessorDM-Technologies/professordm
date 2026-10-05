create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, role, display_name, created_at)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'role', 'creator'),
    coalesce(new.raw_user_meta_data->>'display_name', new.email),
    now()
  );
  return new;
end;
$$ language plpgsql security definer;

create or replace trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();