"""FastAPI app entrypoint. Keep this file thin: wiring only, no business logic."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent.graph import init_graph
from core.checkpoint_lockdown import lock_down_checkpoint_tables
from core.config import settings
from routes import chat, profile, rag, sessions
from services.vector_db import get_vector_db_service

logger = logging.getLogger(__name__)

# Passed to every connection the pool opens for the LangGraph checkpointer:
#   - autocommit: AsyncPostgresSaver manages its own transaction boundaries
#     per checkpoint write; it does not expect to run inside one we opened.
#   - row_factory: the checkpointer's SQL assumes dict-like rows.
#   - prepare_threshold=None: disables psycopg's automatic server-side
#     prepared statements. Required if DATABASE_URL points at a PgBouncer
#     transaction-mode pooler (prepared statements don't survive a
#     connection being handed to a different session mid-transaction); a
#     no-op, harmless safety net against a direct/session-pooler DSN.
_CHECKPOINTER_CONN_KWARGS = {
    "autocommit": True,
    "row_factory": dict_row,
    "prepare_threshold": None,
}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup:
      1. Opens the Qdrant local-mode client (blocking file I/O) off the event
         loop, and once, at startup — instead of lazily on whichever request
         happens to hit it first.
      2. (Phase 6) Opens a dedicated `psycopg_pool.AsyncConnectionPool` against
         `DATABASE_URL` and wraps it in an `AsyncPostgresSaver`, then compiles
         the LangGraph agent graph with it — see `agent/graph.py`. This is the
         *only* place the checkpointer's connection pool is created/closed;
         everything downstream (`services/agent.py`) just calls
         `agent.graph.get_graph()`.

    If `DATABASE_URL` isn't configured, step 2 degrades to compiling the
    graph without a checkpointer (agent still works; no cross-request
    memory) — consistent with how this app treats Supabase itself as
    optional infra elsewhere (see `services/db.py`).
    """
    await asyncio.to_thread(get_vector_db_service)

    pool: AsyncConnectionPool | None = None
    if settings.database_url:
        pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.checkpointer_pool_min_size,
            max_size=settings.checkpointer_pool_max_size,
            kwargs=_CHECKPOINTER_CONN_KWARGS,
            open=False,
        )
        await pool.open(wait=True)
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()  # idempotent: creates/migrates checkpoint tables
        # setup() creates these tables without RLS. Re-apply the lockdown
        # every boot; see core/checkpoint_lockdown.py.
        await lock_down_checkpoint_tables(pool)
        init_graph(checkpointer)
        logger.info("Agent checkpointer ready (DATABASE_URL configured)")
    else:
        logger.warning("DATABASE_URL not set — agent checkpointer disabled, chat memory is request-scoped only")
        init_graph(None)

    try:
        yield
    finally:
        if pool is not None:
            await pool.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    # Explicit list (Phase 5) rather than "*": the frontend now sends a
    # Supabase `Authorization: Bearer <token>` header on every authenticated
    # request (see core/security.py), and browsers only allow a header
    # through a CORS preflight if it's named here (or is one of the small
    # set of always-safelisted headers, which Authorization is not).
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

app.include_router(chat.router)
app.include_router(profile.router)
app.include_router(rag.router)
app.include_router(sessions.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
