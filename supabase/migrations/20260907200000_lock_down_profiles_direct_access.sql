-- Phase 7: remove direct `authenticated`/`anon` access to `public.profiles`.
--
-- Prior state (Phase 5/6): `profiles_select_own`/`profiles_insert_own`/
-- `profiles_update_own` let a signed-in user SELECT/INSERT/UPDATE their own
-- row directly via PostgREST. That was fine for `codeforces_handle`, but
-- for `anthropic_api_key` it meant:
--   1. A client could `UPDATE public.profiles SET anthropic_api_key = ...`
--      with a *plaintext* value directly, completely bypassing the
--      backend's Fernet encryption (`core/crypto.py`) — the column has no
--      trigger enforcing encryption since the
--      20260907180000_fix_profile_encryption_rpc.sql migration moved that
--      responsibility into Python. `upsert_user_profile` was always meant
--      to be the *only* write path; the leftover `profiles_*_own` INSERT/
--      UPDATE policies just never closed the direct one.
--   2. A client could SELECT their own row and get back the encrypted
--      ciphertext blob directly — not a plaintext leak, but also not
--      something the frontend has any legitimate use for now that
--      `GET /api/profile` (backend, service role, masked preview only —
--      see `backend/routes/profile.py`) exists.
--
-- This migration drops those three policies and revokes the underlying
-- table privileges outright (belt-and-suspenders, same posture as the
-- checkpoint-table lockdown in 20260907190000_...): RLS policies alone
-- only gate row *visibility*; revoking INSERT/UPDATE/DELETE/SELECT means
-- `authenticated`/`anon` can't even attempt a statement against this
-- table anymore, policy or no policy.
--
-- What still works after this:
--   - `service_role` (the backend, via `SUPABASE_SECRET_KEY`) is a table
--     owner-equivalent role for RLS purposes and is unaffected — reads
--     continue via `public.profiles_decrypted`
--     (`backend/services/profiles.py`), writes continue via the
--     `SECURITY DEFINER` `upsert_user_profile(uuid, text, text)` RPC
--     (unaffected by this migration; it already runs as the function
--     owner, not the caller).
--   - The frontend's Settings UI continues to work unchanged from the
--     user's point of view, because `SettingsModal.tsx` (Phase 7) was
--     updated to call `GET`/`POST /api/profile` instead of querying
--     `public.profiles` directly.

drop policy if exists "profiles_select_own" on public.profiles;
drop policy if exists "profiles_insert_own" on public.profiles;
drop policy if exists "profiles_update_own" on public.profiles;

revoke select, insert, update, delete on public.profiles from authenticated, anon;

-- RLS stays enabled with zero policies for `authenticated`/`anon` (same
-- "enabled + no policies = deny" posture used for `public.chats` and the
-- LangGraph checkpoint tables elsewhere in this project) as a
-- defense-in-depth backstop in case a future migration re-grants table
-- privileges without thinking through row-level access too.
alter table public.profiles enable row level security;
