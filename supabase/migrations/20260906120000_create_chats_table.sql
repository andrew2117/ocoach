-- Phase 4 Supabase schema: chat history persistence.
-- Run this in the Supabase SQL editor, or via `supabase db push`
-- (see /home/andrew/Projects/ocoach/backend/schema.sql for the Phase 1 schema).

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- chats
-- One row per chat message (both user and assistant turns), grouped by
-- `session_id` — a client-generated UUID identifying one chat thread
-- (see frontend/lib/session.ts). There's intentionally no foreign key to
-- `public.users`/`auth.users`: sessions aren't tied to an authenticated
-- account in this phase, so BYOK users can chat without signing up.
-- ---------------------------------------------------------------------------
create table if not exists public.chats (
    id uuid primary key default gen_random_uuid(),
    session_id text not null,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    created_at timestamptz not null default now()
);

-- Chat history for a session is always fetched ordered by time, so index
-- both columns together rather than just `session_id`.
create index if not exists chats_session_id_created_at_idx
    on public.chats (session_id, created_at);

alter table public.chats enable row level security;

-- No RLS policies are defined here on purpose: `backend/services/db.py`
-- talks to Supabase using the *service role* key, which bypasses RLS
-- entirely, so the backend can always read/write. With RLS enabled and no
-- policies, the `anon`/`authenticated` keys (e.g. if ever exposed to the
-- frontend) get denied by default instead of falling back to Postgres's
-- normal "no RLS = fully open" behavior.
--
-- For local development against a fresh Supabase project where you want to
-- query this table directly from the SQL editor's REST/anon session (not
-- just via the backend), you can temporarily open it up instead:
--
--   create policy "Open access for local development"
--       on public.chats for all
--       using (true)
--       with check (true);
--
-- Don't ship that policy to a shared/production project — it lets anyone
-- with the anon key read and write every session's chat history.
