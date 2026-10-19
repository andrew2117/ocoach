"""Session routes (Phase 5): list/create the signed-in user's chat session
threads, backing the frontend's multi-session sidebar.

Every route here requires a valid Supabase session (`get_current_user`)
and is scoped to that user's `user_id` — see `services/db.py` for why this
application-level scoping, not just Postgres RLS, is what actually
enforces ownership (the backend talks to Supabase with the Secret Key,
key, which bypasses RLS).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.security import AuthenticatedUser, get_current_user
from models.session import CreateSessionRequest, SessionResponse, UpdateSessionRequest
from routes.chat import THREAD_ACCESS_DENIED_DETAIL, _authorize_thread
from services.db import DEFAULT_SESSION_TITLE, get_db_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionResponse])
async def list_sessions(user: AuthenticatedUser = Depends(get_current_user)):
    """Returns the current user's chat sessions, newest first.

    The frontend sidebar groups these client-side by `created_at` (e.g.
    Today / Yesterday / Older) rather than the backend pre-bucketing them,
    so "today" is always evaluated in the viewer's own timezone.
    """
    sessions = await get_db_service().list_sessions(user.user_id)
    return sessions


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    payload: CreateSessionRequest | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Creates a new chat session thread owned by the current user.

    The returned `id` is what the frontend then passes as `session_id` on
    subsequent `/api/chat` calls to group messages under this thread.

    The `sessions` row (with `user_id` stamped on it — see
    `services/db.py::create_session`) is committed to Supabase here,
    synchronously, before this handler returns and therefore strictly
    before any `POST /api/chat`/`GET /api/chat/history` call for this id
    can reach `_authorize_thread` (`routes/chat.py`) or the LangGraph
    checkpointer. That ordering is load-bearing for Phase 7's fail-closed
    thread authorization: a `thread_id` only ever becomes chattable once
    an ownership record for it exists.
    """
    title = (payload.title.strip() if payload and payload.title else "") or DEFAULT_SESSION_TITLE
    session = await get_db_service().create_session(user.user_id, title)
    if session is None:
        raise HTTPException(status_code=503, detail="Could not create a new session right now")
    return session


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    payload: UpdateSessionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Renames a chat session owned by the caller."""
    await _authorize_thread(session_id, user.user_id)

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")

    updated = await get_db_service().update_session_title(session_id, user.user_id, title)
    if updated is None:
        raise HTTPException(status_code=403, detail=THREAD_ACCESS_DENIED_DETAIL)
    return updated


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Deletes a chat session and its UI message log when owned by the caller."""
    await _authorize_thread(session_id, user.user_id)

    deleted = await get_db_service().delete_session(session_id, user.user_id)
    if not deleted:
        raise HTTPException(status_code=403, detail=THREAD_ACCESS_DENIED_DETAIL)
