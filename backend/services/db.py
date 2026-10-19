"""Supabase database service: persists chat history to the `chats` table,
and (Phase 5) manages the `sessions` table backing the multi-session chat
sidebar.

Uses the synchronous `supabase-py` client (there's no first-party async
client), so every call is offloaded to a worker thread via
`asyncio.to_thread` to avoid blocking the event loop — same pattern as the
local Qdrant client in `services/vector_db.py`.

Per the Phase 4 constraints, Supabase is a "nice to have" for this app, not
a hard dependency: if `SUPABASE_URL`/`SUPABASE_SECRET_KEY` aren't configured, or the
Supabase project is unreachable, every method here degrades to a no-op
(`save_message`) or an empty result (`get_chat_history`/`list_sessions`)
instead of raising, so the chat keeps working in-memory-only.

Always constructed with the Supabase Secret Key (`settings.supabase_secret_key`),
which bypasses Postgres RLS — see `routes/chat.py` and `routes/sessions.py`
for the application-level ownership checks that take RLS's place here.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from core.config import settings

logger = logging.getLogger(__name__)

CHATS_TABLE = "chats"
SESSIONS_TABLE = "sessions"
DEFAULT_SESSION_TITLE = "New chat"
AUTO_TITLE_MAX_CHARS = 80

# Process-local counters for chat message persistence outcomes. Not a real
# metrics backend (no StatsD/Prometheus wired up) -- exported via
# `get_persistence_metrics()` so a future exporter (or a debug endpoint)
# has one place to read current counts from, and so Phase 7 callers can
# prove persistence failures are counted, not just logged and forgotten.
_persistence_metrics: dict[str, int] = {"persist_success": 0, "persist_failure": 0}


def get_persistence_metrics() -> dict[str, int]:
    """Returns a snapshot of process-local chat-persistence counters."""
    return dict(_persistence_metrics)


class SessionLookupError(RuntimeError):
    """Raised when a `sessions` ownership lookup cannot be completed
    reliably -- Supabase is unconfigured, unreachable, or the query itself
    errored.

    Deliberately distinct from a legitimate "no such session" result
    (`None`), which is a normal outcome for a `thread_id` that was never
    created. Callers (see `routes/chat.py::_authorize_thread`) MUST treat
    this exception the same as "access denied": Phase 7 hardening replaced
    the previous fail-OPEN behavior (a lookup error or unconfigured
    Supabase silently let the request through) with fail-CLOSED -- an
    infrastructure failure here can never be indistinguishable from
    "allowed by default" again.
    """


class ChatDBService:
    """Wraps a Supabase table for chat message persistence."""

    def __init__(
        self, supabase_url: str | None = None, supabase_secret_key: str | None = None
    ) -> None:
        url = supabase_url if supabase_url is not None else settings.supabase_url
        key = supabase_secret_key if supabase_secret_key is not None else settings.supabase_secret_key

        self._client: Client | None = None
        if not url or not key:
            logger.warning(
                "Supabase not configured (SUPABASE_URL/SUPABASE_SECRET_KEY missing) — "
                "chat history will not be persisted; running in-memory only."
            )
            return

        try:
            self._client = create_client(url, key)
        except Exception:
            logger.exception("Failed to initialize Supabase client — chat history persistence disabled")
            self._client = None

    @property
    def is_enabled(self) -> bool:
        """Whether a Supabase client was successfully configured."""
        return self._client is not None

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Persists one chat message. Never raises to the caller — the
        `POST /api/chat` SSE stream must reach `[DONE]` even if Supabase is
        down — but a failure here is no longer *silent*: it's logged with
        structured fields (`request_id`/`session_id`/`role`/`user_id`) via
        `extra`, so a JSON log pipeline can filter/alert on it, and it's
        counted in `get_persistence_metrics()` so "this has been failing"
        is provable without grepping logs.

        `user_id` (Phase 5) ties the row to its owner so `chats` RLS
        policies can scope access — see the Phase 5 migration. `request_id`
        (Phase 7) correlates this persistence attempt back to the
        originating `POST /api/chat` call in `routes/chat.py`.
        """
        if self._client is None:
            return
        try:
            await asyncio.to_thread(self._insert_message, session_id, role, content, user_id)
            _persistence_metrics["persist_success"] += 1
        except Exception:
            _persistence_metrics["persist_failure"] += 1
            logger.error(
                "Failed to save chat message to Supabase",
                extra={
                    "request_id": request_id,
                    "session_id": session_id,
                    "role": role,
                    "user_id": user_id,
                },
                exc_info=True,
            )

    def _insert_message(self, session_id: str, role: str, content: str, user_id: str | None) -> None:
        row: dict[str, Any] = {"session_id": session_id, "role": role, "content": content}
        if user_id:
            row["user_id"] = user_id
        self._client.table(CHATS_TABLE).insert(row).execute()

    async def get_chat_history(self, session_id: str) -> list[dict[str, Any]]:
        """Returns prior messages for `session_id`, oldest first, as
        `{"role": ..., "content": ...}` dicts. Returns an empty list (rather
        than raising) if Supabase is unconfigured/unreachable or the session
        has no history yet.
        """
        if self._client is None:
            return []
        try:
            return await asyncio.to_thread(self._select_history, session_id)
        except Exception:
            logger.exception("Failed to load chat history from Supabase (session_id=%s)", session_id)
            return []

    def _select_history(self, session_id: str) -> list[dict[str, Any]]:
        response = (
            self._client.table(CHATS_TABLE)
            .select("role, content, created_at")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .execute()
        )
        return [{"role": row["role"], "content": row["content"]} for row in response.data or []]

    # -- Sessions (Phase 5: multi-session chat UI) --------------------------

    async def create_session(self, user_id: str, title: str) -> dict[str, Any] | None:
        """Creates a new chat session thread owned by `user_id`. Returns the
        created row (`id`, `title`, `created_at`), or `None` if Supabase is
        unconfigured/unreachable — the caller (routes/sessions.py) should
        treat that as a 503, since (unlike message persistence) session
        creation has no meaningful in-memory fallback.
        """
        if self._client is None:
            return None
        try:
            return await asyncio.to_thread(self._insert_session, user_id, title)
        except Exception:
            logger.exception("Failed to create session in Supabase (user_id=%s)", user_id)
            return None

    def _insert_session(self, user_id: str, title: str) -> dict[str, Any]:
        response = (
            self._client.table(SESSIONS_TABLE)
            .insert({"user_id": user_id, "title": title})
            .execute()
        )
        return response.data[0]

    async def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """Returns `user_id`'s chat sessions, newest first. Returns an empty
        list (not an error) if Supabase is unconfigured/unreachable.
        """
        if self._client is None:
            return []
        try:
            return await asyncio.to_thread(self._select_sessions, user_id)
        except Exception:
            logger.exception("Failed to list sessions from Supabase (user_id=%s)", user_id)
            return []

    def _select_sessions(self, user_id: str) -> list[dict[str, Any]]:
        response = (
            self._client.table(SESSIONS_TABLE)
            .select("id, title, created_at, updated_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []

    async def get_session_owner(self, session_id: str) -> str | None:
        """Returns the `user_id` that owns `session_id`, or `None` if no
        such session row exists (yet).

        Used to enforce ownership in `routes/chat.py` — the backend talks
        to Supabase with the Supabase Secret Key, which bypasses RLS, so
        this application-level check is what actually stops one signed-in
        user from reading/appending to another user's chat thread (RLS on
        `sessions`/`chats` is a defense-in-depth backstop for direct
        anon/authenticated-key access, not the enforcement point here).

        Phase 7: this is a *security*-critical lookup, unlike every other
        method on this class, so unlike them it does NOT swallow failures
        into a safe-looking default. Raises `SessionLookupError` if
        Supabase is unconfigured or the query itself errors — the caller
        must fail closed on that (deny), never treat it as "no owner
        found, let it through" (see `SessionLookupError`'s docstring and
        `routes/chat.py::_authorize_thread`).
        """
        if self._client is None:
            raise SessionLookupError("Supabase is not configured; cannot verify session ownership")
        try:
            return await asyncio.to_thread(self._select_session_owner, session_id)
        except Exception as exc:
            logger.exception("Failed to look up session owner in Supabase (session_id=%s)", session_id)
            raise SessionLookupError(f"Ownership lookup failed for session_id={session_id}") from exc

    def _select_session_owner(self, session_id: str) -> str | None:
        response = (
            self._client.table(SESSIONS_TABLE)
            .select("user_id")
            .eq("id", session_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0]["user_id"] if rows else None

    async def update_session_title(
        self, session_id: str, user_id: str, title: str
    ) -> dict[str, Any] | None:
        """Renames `session_id` when owned by `user_id`. Returns the updated
        row, or `None` if no such session exists or it belongs to someone
        else. Raises `SessionLookupError` on infra failure (see
        `get_session_owner`).
        """
        owner = await self.get_session_owner(session_id)
        if owner is None or owner != user_id:
            return None
        if self._client is None:
            return None
        try:
            return await asyncio.to_thread(self._update_session_title, session_id, title)
        except Exception:
            logger.exception(
                "Failed to update session title (session_id=%s, user_id=%s)", session_id, user_id
            )
            return None

    def _update_session_title(self, session_id: str, title: str) -> dict[str, Any]:
        response = (
            self._client.table(SESSIONS_TABLE)
            .update({"title": title})
            .eq("id", session_id)
            .execute()
        )
        return response.data[0]

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        """Deletes `session_id` and its UI message log when owned by
        `user_id`. Returns `False` if the session doesn't exist or isn't
        owned. Raises `SessionLookupError` on infra failure.

        LangGraph checkpoint rows for this `thread_id` are intentionally
        not purged here — the checkpointer has no cheap per-thread delete
        API wired up yet; orphaned checkpoint state is inert once the
        `sessions` row is gone because `_authorize_thread` fail-closes on
        the missing ownership record.
        """
        owner = await self.get_session_owner(session_id)
        if owner is None or owner != user_id:
            return False
        if self._client is None:
            return False
        try:
            await asyncio.to_thread(self._delete_session_and_chats, session_id)
            return True
        except Exception:
            logger.exception(
                "Failed to delete session (session_id=%s, user_id=%s)", session_id, user_id
            )
            return False

    def _delete_session_and_chats(self, session_id: str) -> None:
        self._client.table(CHATS_TABLE).delete().eq("session_id", session_id).execute()
        self._client.table(SESSIONS_TABLE).delete().eq("id", session_id).execute()

    async def auto_title_from_first_message(
        self, session_id: str, user_id: str, message: str
    ) -> None:
        """If `session_id` still has the default title, replace it with a
        truncated excerpt of `message`. Best-effort — never raises.
        """
        if self._client is None:
            return
        text = " ".join(message.split()).strip()
        if not text:
            return
        title = text if len(text) <= AUTO_TITLE_MAX_CHARS else f"{text[:AUTO_TITLE_MAX_CHARS].rstrip()}…"
        try:
            await asyncio.to_thread(
                self._auto_title_if_default, session_id, user_id, title
            )
        except Exception:
            logger.exception(
                "Failed to auto-title session (session_id=%s, user_id=%s)", session_id, user_id
            )

    def _auto_title_if_default(self, session_id: str, user_id: str, title: str) -> None:
        response = (
            self._client.table(SESSIONS_TABLE)
            .select("title")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows or rows[0].get("title") != DEFAULT_SESSION_TITLE:
            return
        self._client.table(SESSIONS_TABLE).update({"title": title}).eq("id", session_id).execute()


@lru_cache(maxsize=1)
def get_db_service() -> ChatDBService:
    """Process-wide singleton, mirroring `get_vector_db_service`."""
    return ChatDBService()
