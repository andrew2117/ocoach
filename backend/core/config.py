"""App-wide configuration (env vars, CORS origins, etc.)."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central config loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "OCoach API"

    # Next.js local dev server (see /frontend)
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Supabase (Phase 4: chat history persistence). `supabase_secret_key` is the
    # modern Secret Key (`sb_secret_...`) for backend/server-side use — it
    # bypasses RLS. Never expose it to the frontend, which uses
    # `supabase_anon_key` instead (see frontend/.env.local).
    supabase_url: str = ""
    supabase_anon_key: str = ""
    # `SUPABASE_SERVICE_ROLE_KEY` is accepted as an alias for older runbooks
    # that still use that name. The value is the server secret (`sb_secret_...`
    # or the legacy service-role JWT). Never expose it to the frontend.
    supabase_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )

    # Optional dedicated seed for Fernet-encrypting BYOK API keys in
    # `profiles.anthropic_api_key`. Falls back to `supabase_secret_key`.
    # `core/crypto.py` hashes this string; it is a secret seed, not a
    # pre-encoded Fernet token. `FERNET_ENCRYPTION_KEY` is an alias.
    profile_encryption_key: str = Field(
        default="",
        validation_alias=AliasChoices("PROFILE_ENCRYPTION_KEY", "FERNET_ENCRYPTION_KEY"),
    )

    # RAG / vector DB (Phase 2). Embeddings are NEVER BYOK: the agent's
    # `search_cp_knowledge` tool always uses this server-side key (see
    # `services/tools/rag_tool.py`), and this is also the fallback used by
    # `scripts/ingest.py` when run outside a request context. The only
    # caller-supplied-key path left anywhere is the debug-only
    # `POST /api/rag/search` endpoint's `X-API-Key` header (`routes/rag.py`)
    # -- unrelated to this setting.
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    qdrant_path: str = "qdrant_data"
    qdrant_collection: str = "cp_knowledge"
    # Production Qdrant server (see docker-compose.prod.yml). When `qdrant_host`
    # is set, the client uses the REST API instead of the embedded store at
    # `qdrant_path`. Required for `uvicorn --workers` > 1: local mode holds an
    # exclusive file lock, so a second worker fails on startup. Leave empty
    # for single-process local dev.
    qdrant_host: str = ""
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_https: bool = False
    qdrant_timeout: int = 60

    # Agent (Phase 3, superseded by Phase 5/6/11). BYOK API keys are never
    # accepted from the client directly (no `X-API-Key`) -- they're
    # resolved server-side, per request, from the caller's
    # Fernet-encrypted `profiles` row (`core/crypto.py`,
    # `services/profiles.py`) and threaded into the agent graph as an
    # ephemeral `RunnableConfig.configurable` value that's never persisted
    # to the LangGraph checkpointer (see `agent/graph.py`'s module
    # docstring for why that distinction is load-bearing). Phase 11: which
    # model (and therefore which provider/key) to use per-request is no
    # longer a single global setting here — it's the user's own
    # `profiles.default_model` preference (see `agent/models.py` for the
    # catalog of supported model ids).
    # LangGraph counts each node visit. The coach loop is
    # agent -> tools -> agent -> ...; a limit of 5 allows only ~two tool
    # rounds, which is not enough once `compile_and_test_cpp` runs several
    # stdin cases. 25 is LangGraph's default and leaves room for RAG +
    # multiple compile/test cycles + a final answer.
    agent_recursion_limit: int = 25

    # Phase 6: direct Postgres connection string for the LangGraph
    # `AsyncPostgresSaver` checkpointer (agent memory, keyed by `thread_id`).
    # This is a *different* credential from `supabase_url`/`supabase_secret_key`
    # above — those talk to Supabase's PostgREST/Auth HTTP APIs, whereas the
    # checkpointer needs a raw `postgresql://` DSN (psycopg) to run DDL/DML
    # directly against the underlying database.
    #
    # Use Supabase's *Session* pooler or a direct connection (port 5432), not
    # the *Transaction* pooler (port 6543): PgBouncer transaction mode doesn't
    # support the server-side prepared statements / advisory-lock-adjacent
    # session state the checkpointer's migrations rely on. We already run our
    # own `psycopg_pool.AsyncConnectionPool` in front of this DSN, so pooling
    # is handled application-side regardless of which Supabase endpoint is used.
    #
    # Left empty, the app degrades gracefully (see `backend/main.py`): the
    # agent graph compiles without a checkpointer and chat memory is
    # request-scoped only, same "optional infra" posture as Supabase itself
    # elsewhere in this file.
    database_url: str = ""
    checkpointer_pool_min_size: int = 1
    checkpointer_pool_max_size: int = 10

    # Phase 7: local Piston sandbox for `compile_and_test_cpp` (`agent/tools.py`).
    # Self-hosted only — the public emkc.org Piston API does not issue keys
    # for this project. Default is the Docker container on port 2000; leave
    # empty to disable the tool (it returns an explanatory string to the LLM
    # instead of the app failing to start).
    # Full execute endpoint, not the server root. `PISTON_URL` is an alias and
    # must be that same URL (`http://piston:2000/api/v2/execute` on the
    # compose network). Empty disables the tool.
    piston_api_url: str = Field(
        default="http://localhost:2000/api/v2/execute",
        validation_alias=AliasChoices("PISTON_API_URL", "PISTON_URL"),
    )


settings = Settings()
