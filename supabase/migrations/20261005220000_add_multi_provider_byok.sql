-- Phase 11: multi-provider BYOK (Anthropic, OpenAI, Google Gemini) + a
-- per-user active-model preference.
--
-- Builds on the single-Anthropic-key `profiles` table from
-- 20260907150000_add_auth_profiles_sessions.sql (encryption approach
-- superseded by 20260907180000_fix_profile_encryption_rpc.sql) and the
-- Phase 7 RLS lockdown in 20260907200000_lock_down_profiles_direct_access.sql,
-- which both remain unchanged:
--   - `authenticated`/`anon` still have zero direct privileges on
--     `public.profiles`; all reads/writes continue to go through
--     `profiles_decrypted` (service_role-only) and the `upsert_user_profile`
--     RPC (SECURITY DEFINER), respectively.
--   - Every key column is still just ciphertext (Fernet, encrypted/decrypted
--     in the FastAPI backend — see `backend/core/crypto.py`); Postgres never
--     sees a plaintext key.
--
-- This migration:
--   1. Adds `openai_api_key` and `google_api_key` columns (same shape as the
--      existing `anthropic_api_key`: nullable ciphertext, written only via
--      the RPC below).
--   2. Adds `default_model`, naming which model id (see
--      `backend/agent/models.py::MODEL_CATALOG`) the user's chats should use.
--      Defaults to `'claude-sonnet-5'` so existing single-provider rows keep
--      working unchanged (they already only ever had an Anthropic key).
--   3. Replaces `profiles_decrypted` to surface all three key columns plus
--      `default_model`.
--   4. Replaces `upsert_user_profile(uuid, text, text)` with a 6-arg version
--      that can update any subset of the three keys + `default_model`
--      independently (each defaults to NULL = "leave unchanged"); only
--      `codeforces_handle` keeps the old "always overwrite" semantics.

alter table public.profiles
    add column if not exists openai_api_key text,
    add column if not exists google_api_key text,
    add column if not exists default_model text not null default 'claude-sonnet-5';

-- DROP required: see the identical note in
-- 20260907180000_fix_profile_encryption_rpc.sql — CREATE OR REPLACE VIEW
-- cannot change a view's column list by inserting columns in the middle,
-- and ordering them sensibly (keys grouped, model preference near the
-- handle) is worth the drop/recreate over append-only.
drop view if exists public.profiles_decrypted;

create view public.profiles_decrypted
    with (security_invoker = true)
as
select
    p.user_id,
    p.codeforces_handle,
    p.default_model,
    p.anthropic_api_key,
    p.openai_api_key,
    p.google_api_key,
    p.created_at,
    p.updated_at
from public.profiles p;

revoke all on public.profiles_decrypted from public, anon, authenticated;
grant select on public.profiles_decrypted to service_role;

-- Replace the single-key RPC with a multi-provider one. Both prior
-- overloads are dropped outright (not kept alongside) so there's exactly
-- one `upsert_user_profile` in `pg_proc` — PostgREST resolves RPCs by name
-- + argument-name set, and leaving stale overloads around is a footgun for
-- any caller that forgets to pass the new arguments.
--   - `(uuid, text, text)`: the tracked 3-arg version from
--     20260907180000_fix_profile_encryption_rpc.sql.
--   - `(text, text)`: an untracked, pre-RPC-hardening leftover (took
--     `cf_handle`/`api_key` and called `auth.uid()` directly instead of
--     `p_user_id`) found live on the project but never captured in a
--     migration file; dropped here too so it doesn't linger as dead,
--     divergent-behavior code once this migration lands.
drop function if exists public.upsert_user_profile(uuid, text, text);
drop function if exists public.upsert_user_profile(text, text);

create or replace function public.upsert_user_profile(
    p_user_id uuid,
    p_cf_handle text default null,
    p_anthropic_api_key text default null,
    p_openai_api_key text default null,
    p_google_api_key text default null,
    p_default_model text default null
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
    v_anthropic_api_key text;
    v_openai_api_key text;
    v_google_api_key text;
    v_default_model text;
begin
    v_anthropic_api_key := nullif(btrim(coalesce(p_anthropic_api_key, '')), '');
    v_openai_api_key := nullif(btrim(coalesce(p_openai_api_key, '')), '');
    v_google_api_key := nullif(btrim(coalesce(p_google_api_key, '')), '');
    v_default_model := nullif(btrim(coalesce(p_default_model, '')), '');

    insert into public.profiles (
        user_id,
        codeforces_handle,
        anthropic_api_key,
        openai_api_key,
        google_api_key,
        default_model
    )
    values (
        p_user_id,
        nullif(btrim(p_cf_handle), ''),
        v_anthropic_api_key,
        v_openai_api_key,
        v_google_api_key,
        coalesce(v_default_model, 'claude-sonnet-5')
    )
    on conflict (user_id) do update
    set
        codeforces_handle = excluded.codeforces_handle,
        -- Each key/preference is only overwritten when a new, non-blank
        -- value was actually passed; omitting a field (NULL) leaves the
        -- existing stored value in place rather than clearing it.
        anthropic_api_key = coalesce(v_anthropic_api_key, profiles.anthropic_api_key),
        openai_api_key = coalesce(v_openai_api_key, profiles.openai_api_key),
        google_api_key = coalesce(v_google_api_key, profiles.google_api_key),
        default_model = coalesce(v_default_model, profiles.default_model),
        updated_at = now();
end;
$$;

alter function public.upsert_user_profile(uuid, text, text, text, text, text) owner to postgres;

revoke all on function public.upsert_user_profile(uuid, text, text, text, text, text) from public;
grant execute on function public.upsert_user_profile(uuid, text, text, text, text, text) to service_role;
