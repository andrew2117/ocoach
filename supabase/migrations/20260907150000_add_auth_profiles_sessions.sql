-- Phase 5 Supabase schema: Auth-backed profiles + multi-session chat, with
-- encrypted-at-rest BYOK storage.
-- Run via `supabase db push`, or paste into the Supabase SQL editor.
--
-- This migration:
--   1. Adds `public.profiles` (one row per `auth.users`) holding the user's
--      BYOK Anthropic API key (encrypted at rest via pgsodium) and
--      Codeforces handle.
--   2. Adds `public.sessions` (one row per chat thread) so the frontend
--      sidebar can list/group a user's previous chats.
--   3. Adds `user_id` to the existing `public.chats` table (Phase 4) so
--      individual messages can be tied back to an owner.
--   4. Enables strict Row Level Security everywhere: `auth.uid() = user_id`
--      for select/insert (and update where relevant) on every table.
--
-- A note on encryption approach: pgsodium's `SECURITY LABEL ... ENCRYPT
-- WITH KEY ID` masking feature relies on an event trigger that needs
-- superuser/extension-owner privileges to install, which hosted Supabase
-- projects don't grant to the `postgres` migration role. Instead, this
-- migration wires up the *same* pgsodium primitives (a named key +
-- deterministic AEAD encrypt/decrypt) explicitly, via a BEFORE INSERT/
-- UPDATE trigger (encrypt) and a service-role-only view (decrypt) — this is
-- "transparent" from the application's point of view (plain INSERT/SELECT
-- statements), which is what actually matters, without requiring
-- privileges hosted Supabase doesn't grant.

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
create extension if not exists "pgcrypto"; -- gen_random_uuid()
create extension if not exists "pgsodium"; -- column encryption primitives

-- ---------------------------------------------------------------------------
-- Shared helper: keep `updated_at` current on every UPDATE.
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- profiles
-- One row per authenticated user. `anthropic_api_key` is stored encrypted
-- at rest (see the pgsodium section below) — the plaintext key is only
-- ever visible to callers with `service_role` (i.e. the FastAPI backend),
-- via `public.profiles_decrypted`, never directly from this table and
-- never to the `anon`/`authenticated` Postgres roles the frontend uses.
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
    user_id uuid primary key references auth.users (id) on delete cascade,
    codeforces_handle text,
    -- Ciphertext (base64), written by the `profiles_encrypt_anthropic_api_key`
    -- trigger below. Never store a plaintext key here directly.
    anthropic_api_key text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Strict RLS: a user may only ever see/create/modify their own row.
create policy "profiles_select_own"
    on public.profiles for select
    using (auth.uid() = user_id);

create policy "profiles_insert_own"
    on public.profiles for insert
    with check (auth.uid() = user_id);

create policy "profiles_update_own"
    on public.profiles for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- Intentionally no delete policy: the app never needs to delete a profile
-- row directly (it cascades away if the auth.users row is deleted).

create trigger profiles_set_updated_at
    before update on public.profiles
    for each row
    execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- pgsodium: transparent column encryption for profiles.anthropic_api_key
-- ---------------------------------------------------------------------------

-- A single named, deterministic-AEAD key dedicated to this column. Created
-- once and looked up by name thereafter — `pgsodium.create_key` returns
-- the raw key material to the *caller* only at creation time; the row
-- pgsodium stores internally (`pgsodium.key`) never exposes secret bytes
-- back out over SQL, so granting SELECT on it below (to look up the id) is
-- safe.
do $$
begin
    if not exists (
        select 1 from pgsodium.key where name = 'profiles_anthropic_api_key'
    ) then
        perform pgsodium.create_key(
            name := 'profiles_anthropic_api_key',
            key_type := 'aead-det'
        );
    end if;
end;
$$;

-- Encrypts `anthropic_api_key` in place before it's written. Runs as
-- `security definer` (owned by the migration role, which has pgsodium
-- access) so ordinary `authenticated` callers performing a normal
-- `insert`/`update` don't need direct grants on the `pgsodium` schema.
-- Binds the ciphertext to `user_id` as associated data so a ciphertext
-- value can't be copied into a different user's row and decrypt cleanly.
create or replace function public.encrypt_profile_anthropic_api_key()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_key_id uuid;
begin
    if new.anthropic_api_key is null or new.anthropic_api_key = '' then
        new.anthropic_api_key := null;
        return new;
    end if;

    select id into v_key_id from pgsodium.key where name = 'profiles_anthropic_api_key';
    if v_key_id is null then
        raise exception 'pgsodium key "profiles_anthropic_api_key" is missing';
    end if;

    new.anthropic_api_key := encode(
        pgsodium.crypto_aead_det_encrypt(
            convert_to(new.anthropic_api_key, 'utf8'),
            convert_to(new.user_id::text, 'utf8'),
            v_key_id
        ),
        'base64'
    );
    return new;
end;
$$;

-- `update of anthropic_api_key` means an UPDATE that only touches
-- `codeforces_handle` never re-runs this (and can't accidentally
-- double-encrypt already-ciphertext bytes).
create trigger profiles_encrypt_anthropic_api_key
    before insert or update of anthropic_api_key on public.profiles
    for each row
    execute function public.encrypt_profile_anthropic_api_key();

-- Secret-key-only decrypting view. The FastAPI backend (using
-- `SUPABASE_SECRET_KEY`) reads BYOK keys exclusively through this view —
-- see `backend/services/profiles.py`.
create or replace view public.profiles_decrypted
    with (security_invoker = true)
as
select
    p.user_id,
    p.codeforces_handle,
    case
        when p.anthropic_api_key is null then null
        else convert_from(
            pgsodium.crypto_aead_det_decrypt(
                decode(p.anthropic_api_key, 'base64'),
                convert_to(p.user_id::text, 'utf8'),
                (select id from pgsodium.key where name = 'profiles_anthropic_api_key')
            ),
            'utf8'
        )
    end as anthropic_api_key,
    p.created_at,
    p.updated_at
from public.profiles p;

revoke all on public.profiles_decrypted from public, anon, authenticated;
grant select on public.profiles_decrypted to service_role;
grant usage on schema pgsodium to service_role;
grant select on pgsodium.key to service_role;

-- ---------------------------------------------------------------------------
-- sessions
-- One row per chat thread, owned by exactly one user. The frontend sidebar
-- lists these (grouped client-side by `created_at`); `public.chats.session_id`
-- (Phase 4, still a free-form text id) is expected to hold this row's `id`
-- (as text) once a session is created via POST /api/sessions.
-- ---------------------------------------------------------------------------
create table if not exists public.sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    title text not null default 'New chat',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists sessions_user_id_created_at_idx
    on public.sessions (user_id, created_at desc);

alter table public.sessions enable row level security;

create policy "sessions_select_own"
    on public.sessions for select
    using (auth.uid() = user_id);

create policy "sessions_insert_own"
    on public.sessions for insert
    with check (auth.uid() = user_id);

create policy "sessions_update_own"
    on public.sessions for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create policy "sessions_delete_own"
    on public.sessions for delete
    using (auth.uid() = user_id);

create trigger sessions_set_updated_at
    before update on public.sessions
    for each row
    execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- chats: add ownership, tighten RLS
-- ---------------------------------------------------------------------------
alter table public.chats
    add column if not exists user_id uuid references auth.users (id) on delete set null;

create index if not exists chats_user_id_idx on public.chats (user_id);

-- Phase 4 shipped this table with RLS enabled but *no* policies (see the
-- comment in the original migration) so that only the backend's
-- service-role key — which bypasses RLS entirely — could read/write it.
-- Phase 5 adds real policies now that rows carry `user_id`, as a
-- defense-in-depth backstop should the table ever be queried directly with
-- the anon/authenticated key. The backend remains the primary enforcement
-- point (service role bypasses RLS, so it does its own `user_id` checks —
-- see `backend/routes/chat.py`).
create policy "chats_select_own"
    on public.chats for select
    using (auth.uid() = user_id);

create policy "chats_insert_own"
    on public.chats for insert
    with check (auth.uid() = user_id);

-- Note: pre-Phase-5 rows have `user_id is null`. `auth.uid() = user_id` is
-- never true against `null`, so those legacy rows simply become
-- inaccessible via the anon/authenticated key (still fully readable by the
-- backend's service-role key) rather than silently open.
