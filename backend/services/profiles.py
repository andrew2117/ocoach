"""Phase 5: Supabase-backed user profile service (BYOK API keys + model
preference + Codeforces handle).

Phase 11 made this multi-provider: `profiles` now holds one encrypted
column per provider (`anthropic_api_key`, `openai_api_key`,
`google_api_key`) plus a `default_model` text column naming which model id
(see `agent/models.py::MODEL_CATALOG`) the user wants the agent to use.

Reads go through the `profiles_decrypted` view (service_role only). API keys
are Fernet-encrypted by the backend before write and decrypted on read — hosted
Supabase does not allow pgsodium encrypt from SQL. The frontend never writes
keys directly; profile saves go through `routes/profile.py`, which calls the
`upsert_user_profile` RPC via the Secret Key.

Uses the synchronous `supabase-py` client, offloaded to a worker thread via
`asyncio.to_thread`, same pattern as `services/db.py`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import lru_cache

from typing import Any

from supabase import Client, create_client

from agent.models import DEFAULT_MODEL_ID, ModelProvider
from core.config import settings
from core.crypto import decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)

PROFILES_DECRYPTED_VIEW = "profiles_decrypted"
UPSERT_PROFILE_RPC = "upsert_user_profile"


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    anthropic_api_key: str | None
    openai_api_key: str | None
    google_api_key: str | None
    codeforces_handle: str | None
    default_model: str

    @property
    def has_anthropic_key(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.strip())

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())

    @property
    def has_google_key(self) -> bool:
        return bool(self.google_api_key and self.google_api_key.strip())

    @property
    def has_any_api_key(self) -> bool:
        return self.has_anthropic_key or self.has_openai_key or self.has_google_key

    @property
    def api_keys(self) -> dict[str, str]:
        """`{"anthropic"|"openai"|"google": "<decrypted key>"}`, omitting
        any provider with no saved key. This is the exact shape threaded
        into the agent graph's `config.configurable["api_keys"]` — see
        `agent/graph.py`'s module docstring and `routes/chat.py`.
        """
        pairs = (
            (ModelProvider.ANTHROPIC.value, self.anthropic_api_key),
            (ModelProvider.OPENAI.value, self.openai_api_key),
            (ModelProvider.GOOGLE.value, self.google_api_key),
        )
        return {provider: key for provider, key in pairs if key and key.strip()}

    def has_key_for(self, provider: ModelProvider) -> bool:
        return provider.value in self.api_keys


class ProfileDBService:
    """Wraps the `profiles_decrypted` view for BYOK profile lookups.

    Must be constructed with the Supabase Secret Key (`sb_secret_...`) — the
    decrypting view's grants deny `anon`/`authenticated`, so any other key
    will simply see zero rows (PostgREST returns an empty/forbidden result
    rather than an error), which this service surfaces as `None`.
    """

    def __init__(
        self, supabase_url: str | None = None, supabase_secret_key: str | None = None
    ) -> None:
        url = supabase_url if supabase_url is not None else settings.supabase_url
        key = supabase_secret_key if supabase_secret_key is not None else settings.supabase_secret_key

        self._client: Client | None = None
        if not url or not key:
            logger.warning(
                "Supabase not configured (SUPABASE_URL/SUPABASE_SECRET_KEY missing) — "
                "BYOK profile lookups will always report no key configured."
            )
            return

        try:
            self._client = create_client(url, key)
        except Exception:
            logger.exception("Failed to initialize Supabase client — profile lookups disabled")
            self._client = None

    @property
    def is_enabled(self) -> bool:
        return self._client is not None

    async def get_profile(self, user_id: str) -> UserProfile | None:
        """Returns `user_id`'s decrypted profile, or `None` if they have no
        profile row yet, or Supabase is unconfigured/unreachable. Never
        raises — callers should treat `None` (or `has_any_api_key=False`)
        the same as "not configured yet" and prompt the user accordingly.
        """
        if self._client is None:
            return None
        try:
            return await asyncio.to_thread(self._select_profile, user_id)
        except Exception:
            logger.exception("Failed to load profile from Supabase (user_id=%s)", user_id)
            return None

    async def upsert_profile(
        self,
        user_id: str,
        codeforces_handle: str | None,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        google_api_key: str | None = None,
        default_model: str | None = None,
    ) -> None:
        """Creates or updates `user_id`'s profile via the `upsert_user_profile`
        RPC. Each API key is Fernet-encrypted in Python before it reaches
        Postgres.

        For every parameter except `codeforces_handle`, passing `None`
        leaves the existing stored value unchanged (`codeforces_handle` is
        always overwritten — including to `None`/cleared — matching the
        pre-Phase-11 behavior for that field). This lets a caller update
        just the OpenAI key, say, without having to resend the Anthropic
        and Google keys or re-select a model.
        """
        if self._client is None:
            raise RuntimeError("Supabase client is not configured")
        await asyncio.to_thread(
            self._upsert_profile,
            user_id,
            codeforces_handle,
            anthropic_api_key,
            openai_api_key,
            google_api_key,
            default_model,
        )

    def _upsert_profile(
        self,
        user_id: str,
        codeforces_handle: str | None,
        anthropic_api_key: str | None,
        openai_api_key: str | None,
        google_api_key: str | None,
        default_model: str | None,
    ) -> None:
        params: dict[str, Any] = {
            "p_user_id": user_id,
            "p_cf_handle": codeforces_handle,
            "p_anthropic_api_key": encrypt_api_key(anthropic_api_key) if anthropic_api_key else None,
            "p_openai_api_key": encrypt_api_key(openai_api_key) if openai_api_key else None,
            "p_google_api_key": encrypt_api_key(google_api_key) if google_api_key else None,
            "p_default_model": default_model,
        }
        self._client.rpc(UPSERT_PROFILE_RPC, params).execute()

    def _select_profile(self, user_id: str) -> UserProfile | None:
        response = (
            self._client.table(PROFILES_DECRYPTED_VIEW)
            .select("user_id, anthropic_api_key, openai_api_key, google_api_key, codeforces_handle, default_model")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        row = rows[0]

        def _decrypt(column: str) -> str | None:
            raw = row.get(column)
            return decrypt_api_key(raw) if raw else None

        return UserProfile(
            user_id=row["user_id"],
            anthropic_api_key=_decrypt("anthropic_api_key"),
            openai_api_key=_decrypt("openai_api_key"),
            google_api_key=_decrypt("google_api_key"),
            codeforces_handle=row.get("codeforces_handle"),
            default_model=row.get("default_model") or DEFAULT_MODEL_ID,
        )


@lru_cache(maxsize=1)
def get_profile_service() -> ProfileDBService:
    """Process-wide singleton, mirroring `get_db_service`."""
    return ProfileDBService()
