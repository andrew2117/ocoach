-- Replace pgsodium column encryption (blocked on hosted Supabase — postgres
-- cannot call crypto_aead_det_encrypt even in the SQL editor).
--
-- API keys are now Fernet-encrypted by the FastAPI backend before insert.
-- This migration:
--   1. Removes the pgsodium BEFORE INSERT/UPDATE trigger.
--   2. Replaces `profiles_decrypted` with a service_role-only passthrough view.
--   3. Adds `upsert_user_profile(user_id, cf_handle, api_key)` — plain SQL,
--      no pgsodium calls, safe to run in the Supabase SQL editor.

drop trigger if exists profiles_encrypt_anthropic_api_key on public.profiles;
drop function if exists public.encrypt_profile_anthropic_api_key();

-- DROP required: CREATE OR REPLACE cannot change column collation when the
-- old view used convert_from(...) ("C") vs a direct text column ("default").
drop view if exists public.profiles_decrypted;

create view public.profiles_decrypted
    with (security_invoker = true)
as
select
    p.user_id,
    p.codeforces_handle,
    p.anthropic_api_key,
    p.created_at,
    p.updated_at
from public.profiles p;

revoke all on public.profiles_decrypted from public, anon, authenticated;
grant select on public.profiles_decrypted to service_role;

create or replace function public.upsert_user_profile(
    p_user_id uuid,
    p_cf_handle text default null,
    p_api_key text default null
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
    v_api_key text;
begin
    if p_api_key is not null then
        v_api_key := btrim(p_api_key);
        if v_api_key = '' then
            v_api_key := null;
        end if;
    end if;

    if v_api_key is not null then
        insert into public.profiles (user_id, codeforces_handle, anthropic_api_key)
        values (p_user_id, nullif(btrim(p_cf_handle), ''), v_api_key)
        on conflict (user_id) do update
        set
            codeforces_handle = excluded.codeforces_handle,
            anthropic_api_key = excluded.anthropic_api_key,
            updated_at = now();
    else
        insert into public.profiles (user_id, codeforces_handle)
        values (p_user_id, nullif(btrim(p_cf_handle), ''))
        on conflict (user_id) do update
        set
            codeforces_handle = excluded.codeforces_handle,
            updated_at = now();
    end if;
end;
$$;

alter function public.upsert_user_profile(uuid, text, text) owner to postgres;

revoke all on function public.upsert_user_profile(uuid, text, text) from public;
grant execute on function public.upsert_user_profile(uuid, text, text) to service_role;
