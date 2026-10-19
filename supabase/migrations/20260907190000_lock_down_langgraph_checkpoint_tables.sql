-- Phase 6: lock down the LangGraph `AsyncPostgresSaver` checkpointer tables.
--
-- `checkpointer.setup()` (called once at FastAPI startup — see
-- `backend/main.py`) creates `checkpoints`, `checkpoint_blobs`,
-- `checkpoint_writes`, and `checkpoint_migrations` directly via
-- `CREATE TABLE IF NOT EXISTS` (unqualified => the `public` schema, since
-- that library has no schema-namespacing option). It does NOT enable RLS or
-- touch grants.
--
-- Supabase projects configure default privileges so that any new table
-- created in `public` is automatically readable/writable by the `anon` and
-- `authenticated` PostgREST roles (the same reason `chats` and `profiles`
-- lock themselves down explicitly — see
-- `supabase/migrations/20260906120000_create_chats_table.sql` and
-- `20260907150000_add_auth_profiles_sessions.sql`). Left alone, these four
-- tables would otherwise be readable over `/rest/v1/checkpoints` etc. by
-- anyone holding the anon key — a direct leak of every user's full agent
-- conversation state (including tool call inputs/outputs), independent of
-- the pgsodium/TCE work done for `profiles.anthropic_api_key`.
--
-- Run this AFTER the backend has started at least once against this
-- database (so `checkpointer.setup()` has created the tables) — each block
-- below is a no-op if its table doesn't exist yet, so it's also safe to run
-- speculatively beforehand and simply re-run after.
--
-- Note on who can still read/write normally: the backend's `DATABASE_URL`
-- role owns these tables (it's the role that ran `CREATE TABLE`), and table
-- owners bypass RLS by default — so the checkpointer itself is unaffected.
-- This migration only removes the *PostgREST/anon/authenticated* path.

do $$
declare
    t text;
begin
    foreach t in array array['checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoint_migrations']
    loop
        if to_regclass('public.' || t) is not null then
            execute format('alter table public.%I enable row level security', t);
            execute format('revoke all on public.%I from anon, authenticated', t);
            -- No policies defined on purpose (same posture as `public.chats`):
            -- RLS-enabled + zero policies denies anon/authenticated outright,
            -- while the owning role (DATABASE_URL) and service_role remain
            -- unaffected.
        end if;
    end loop;
end;
$$;
