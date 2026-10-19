"""Re-lock LangGraph checkpoint tables after ``AsyncPostgresSaver.setup()``.

``checkpointer.setup()`` creates ``public.checkpoints`` and its siblings with
``CREATE TABLE IF NOT EXISTS``. On Supabase that inherits default privileges
for ``anon`` and ``authenticated`` and does not enable RLS, so the Data API
can read every thread's agent state until something revokes that access.

``supabase/migrations/20260907190000_lock_down_langgraph_checkpoint_tables.sql``
only helps when the tables already exist at migration time. This runs the
same statements on every process start, immediately after ``setup()``, so the
window does not depend on migration order. Table owners (the ``DATABASE_URL``
role) bypass RLS, so the checkpointer itself keeps working. RLS is not forced.
"""

from __future__ import annotations

import logging

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

_CHECKPOINT_TABLES = (
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
)

_LOCKDOWN_SQL = """
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
"""


async def lock_down_checkpoint_tables(pool: AsyncConnectionPool) -> None:
    """Enables RLS and drops Data API grants on the checkpointer tables.

    Idempotent. Failures are logged and swallowed: a lockdown error must not
    prevent the API from booting, but it is visible in logs because the
    tables would otherwise stay readable through PostgREST.
    """
    try:
        async with pool.connection() as conn:
            connection: AsyncConnection = conn
            await connection.execute(_LOCKDOWN_SQL)
    except Exception:
        logger.exception(
            "Failed to lock down LangGraph checkpoint tables; anon/authenticated "
            "may still be able to read them via the Data API"
        )
        return

    logger.info(
        "Checkpoint tables locked down (RLS on, anon/authenticated revoked): %s",
        ", ".join(_CHECKPOINT_TABLES),
    )
