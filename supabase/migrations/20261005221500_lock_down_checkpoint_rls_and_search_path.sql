-- Advisor follow-up (security lints rls_disabled_in_public and
-- function_search_path_mutable).
--
-- 1. LangGraph checkpoint tables. `20260907190000_lock_down_langgraph_checkpoint_tables.sql`
--    enables RLS and revokes anon/authenticated only when the tables already
--    exist. They don't, at migration time: `AsyncPostgresSaver.setup()`
--    creates them later (`CREATE TABLE IF NOT EXISTS` in `public`) and
--    Supabase default privileges then grant anon/authenticated full DML with
--    RLS still off. Re-run the same lockdown here, now that the tables exist.
--    The FastAPI lifespan repeats this SQL after every `setup()` so a fresh
--    database doesn't stay exposed until the next migration
--    (`backend/core/checkpoint_lockdown.py`).
--
--    No policies on purpose. The checkpointer connects as the table owner
--    via DATABASE_URL, and owners bypass RLS. anon/authenticated must not
--    read agent transcripts through PostgREST. Do not FORCE ROW LEVEL
--    SECURITY: that would also deny the owning role and break chat memory.
--
-- 2. `public.set_updated_at` had no fixed search_path, so a caller could
--    shadow `now()` via their role's search_path. Pin it empty; `now()`
--    still resolves from pg_catalog.

do $$
declare
    t text;
begin
    foreach t in array array[
        'checkpoints',
        'checkpoint_blobs',
        'checkpoint_writes',
        'checkpoint_migrations'
    ]
    loop
        if to_regclass('public.' || t) is not null then
            execute format('alter table public.%I enable row level security', t);
            execute format('revoke all on table public.%I from anon, authenticated', t);
        end if;
    end loop;
end;
$$;

alter function public.set_updated_at() set search_path = '';
