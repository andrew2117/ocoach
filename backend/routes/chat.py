"""Chat routes: receives a message, runs it through the LangGraph CP coach
agent, and streams the reply back over SSE.

Phase 3 replaced the Phase 2 mock reply with a real agent loop
(`services/agent.py`) that dynamically calls tools — including the Phase 2
RAG search, now exposed as the `search_cp_knowledge` tool — based on intent,
rather than unconditionally running retrieval before every reply.

Phase 5 makes the endpoint require Supabase Auth: every request must carry
a valid `Authorization: Bearer <supabase-access-token>` header (verified in
`core/security.py`). The caller's BYOK API key(s) are no longer accepted
from the client at all (no more `X-API-Key`) — they're looked up
server-side from the user's encrypted `profiles` row
(`services/profiles.py`), using the backend's Supabase Secret Key,
so the frontend never handles a raw key beyond the one time the user
types it into Settings. A user with no key saved for any provider yet gets
a `403` naming the problem so the frontend can prompt them to open
Settings, rather than a generic auth failure.

Phase 6 replaced the Phase 4 "manually reload history, hand it to the agent"
approach with the LangGraph `AsyncPostgresSaver` checkpointer: every request
now requires a `thread_id` (a `sessions.id` UUID, see `models/chat.py`),
which the graph itself uses to recall prior turns — see `services/agent.py`.
This route still writes to the Supabase `chats` table via `_persist_turn`,
but that's now solely for the frontend's message-log UI
(`GET /api/chat/history/{thread_id}`); it is no longer read back into the
agent's context.

Phase 11 made the chat model multi-provider (BYOK Anthropic, OpenAI, or
Google Gemini, user-selectable via `profiles.default_model`): this route
resolves *all* saved provider keys plus the selected model id
(`_resolve_byok_profile`) and hands both to `services/agent.py`, which
picks the one provider key the selected model actually needs.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from core.security import AuthenticatedUser, get_current_user
from models.chat import ChatRequest
from services.agent import stream_agent_reply
from services.db import SessionLookupError, get_db_service
from services.profiles import get_profile_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

PROFILE_INCOMPLETE_DETAIL = {
    "error": "profile_incomplete",
    "message": (
        "No API key is configured for your account yet. Open Settings and add an "
        "API key for at least one provider (Anthropic, OpenAI, or Google) to start chatting."
    ),
}


def _sse_frame(text: str) -> str:
    """Formats `text` as one SSE frame, per the `text/event-stream` spec.

    Multi-line payloads (e.g. code blocks in the LLM's reply) need one
    `data:` line per line of text — a bare embedded blank line would
    otherwise prematurely terminate the frame, since `\\n\\n` is the frame
    delimiter.
    """
    payload = "\n".join(f"data: {line}" for line in text.split("\n"))
    return f"{payload}\n\n"


async def _persist_turn(
    session_id: str,
    user_id: str,
    user_message: str,
    assistant_reply: str,
    request_id: str,
) -> None:
    """Saves both sides of a chat turn to Supabase. Runs as a fire-and-forget
    background task (see `chat()`) so persistence never delays the SSE
    stream reaching its `[DONE]` sentinel; `save_message` itself never
    raises, so this can't crash silently in a way that matters. `request_id`
    ties any failure logged here back to the originating `POST /api/chat`
    call (see `services/db.py::save_message`).
    """
    db = get_db_service()
    await db.save_message(session_id, "user", user_message, user_id=user_id, request_id=request_id)
    await db.auto_title_from_first_message(session_id, user_id, user_message)
    if assistant_reply:
        await db.save_message(
            session_id, "assistant", assistant_reply, user_id=user_id, request_id=request_id
        )


async def agent_chat_stream(
    message: str,
    api_keys: dict[str, str],
    default_model: str,
    codeforces_handle: str | None,
    thread_id: str,
    user_id: str,
    request_id: str,
) -> AsyncGenerator[str, None]:
    """Runs the LangGraph agent and yields SSE frames of its reply, word for
    word as tokens arrive, ending with a `[DONE]` sentinel frame.

    Accumulates the full reply as it streams so the complete turn (user
    message + assistant reply) can be persisted to Supabase afterwards, for
    the frontend's message-log UI (the agent's own memory of this turn is
    the checkpointer's job — see `services/agent.py` — not this persistence
    call). `request_id` is a per-request correlation id (generated once in
    `chat()`) threaded through to both the error log below and to
    `_persist_turn`, so a given SSE call's server-side error and its
    persistence outcome can be grepped/joined by one value.
    """
    reply_chunks: list[str] = []
    try:
        async for event in stream_agent_reply(
            message,
            api_keys=api_keys,
            thread_id=thread_id,
            default_model=default_model,
            codeforces_handle=codeforces_handle,
        ):
            if event.get("type") == "token":
                reply_chunks.append(event.get("content", ""))
            yield _sse_frame(json.dumps(event))
    except Exception as exc:
        # Belt-and-suspenders: `stream_agent_reply` already catches its own
        # errors and yields them as text, but this guards against anything
        # unexpected happening in the generator/streaming machinery itself.
        logger.exception(
            "Unhandled error while streaming agent reply",
            extra={"request_id": request_id, "thread_id": thread_id, "user_id": user_id},
        )
        yield _sse_frame(f"(Unexpected server error: {exc})")
    finally:
        # Fired off rather than awaited so a slow/unreachable Supabase can't
        # delay the client from seeing [DONE].
        asyncio.create_task(
            _persist_turn(thread_id, user_id, message, "".join(reply_chunks), request_id)
        )
        yield "data: [DONE]\n\n"


async def _resolve_byok_profile(user_id: str) -> tuple[dict[str, str], str, str | None]:
    """Looks up `user_id`'s BYOK API keys, selected model, and Codeforces
    handle from their encrypted profile.

    Raises the Phase 5 `403 profile_incomplete` response if the profile has
    *no* API key saved for any provider yet — this is deliberately a
    distinct, machine-readable error (not a bare 401/400) so the frontend
    can catch it and open the Settings modal instead of showing a generic
    error toast. A profile with a key for e.g. Anthropic but a
    `default_model` pointing at an OpenAI model is let through here (it has
    *a* key, just not the one its selected model needs) — that
    provider-specific case is instead reported with a clean, named-model
    message from `services/agent.py::stream_agent_reply` mid-stream, since
    it depends on which model the caller has selected, not just whether
    they've been to Settings at all.
    """
    profile = await get_profile_service().get_profile(user_id)
    if profile is None or not profile.has_any_api_key:
        raise HTTPException(status_code=403, detail=PROFILE_INCOMPLETE_DETAIL)
    return profile.api_keys, profile.default_model, profile.codeforces_handle


THREAD_ACCESS_DENIED_DETAIL = "Thread access denied or session not found"


async def _authorize_thread(thread_id: str, user_id: str) -> None:
    """Verifies `user_id` owns `thread_id` (a `sessions.id`) — fail CLOSED.

    Phase 7 hardening: this used to let a `thread_id` with no matching
    `sessions` row through unchallenged (reasoning: the same id doubles as
    the LangGraph checkpointer's `thread_id`, so rejecting it seemed
    overly strict). That was actually a critical gap — nothing then
    stopped an authenticated caller from picking an arbitrary/guessed UUID
    and having the checkpointer silently start (or, worse, continue)
    agent memory under it with no ownership record at all, and a Supabase
    outage during the lookup (`SessionLookupError`) was *also* previously
    swallowed into "no owner found" and let through the exact same way.

    Both cases are now denied. A caller MUST create the session first via
    `POST /api/sessions` (which stamps `user_id` on it — see
    `services/db.py::create_session`) before chatting or reading history
    against its id; an ownership lookup that can't be completed is treated
    identically to "not yours". This is also what actually gives the
    checkpointer's `thread_id` its tenant isolation: the `checkpoints*`
    tables themselves carry no `user_id` column (see
    `supabase/migrations/20260907190000_lock_down_langgraph_checkpoint_tables.sql`),
    so this check — run before the graph is ever invoked for a given
    `thread_id`, on every `/api/chat` and `/api/chat/history` request — is
    the sole enforcement point standing between tenants for that state.

    Deliberately returns the same generic detail message on both "no such
    session" and "belongs to someone else" (`THREAD_ACCESS_DENIED_DETAIL`)
    so this endpoint can't be used to enumerate which session ids exist.
    """
    try:
        owner = await get_db_service().get_session_owner(thread_id)
    except SessionLookupError:
        logger.warning(
            "Session ownership lookup failed for thread_id=%s; denying access (fail-closed)",
            thread_id,
        )
        raise HTTPException(status_code=403, detail=THREAD_ACCESS_DENIED_DETAIL) from None

    if owner is None or owner != user_id:
        raise HTTPException(status_code=403, detail=THREAD_ACCESS_DENIED_DETAIL)


@router.post("/chat")
async def chat(payload: ChatRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """Streams a chat response over Server-Sent Events.

    Requires a valid Supabase session (`Authorization: Bearer <token>`).
    The BYOK API key(s) and selected model are resolved server-side from
    the caller's `profiles` row — never accepted from the request itself,
    and never placed in the LangGraph state that `payload.thread_id`
    checkpoints (see `agent/graph.py`). If `payload.codeforces_handle` is
    omitted, the handle saved in the caller's profile is used instead.

    `payload.thread_id` scopes the agent's persistent memory: the
    checkpointer recalls prior turns for that thread automatically (no
    manual history reload). This turn's user message and the agent's full
    reply are also saved to Supabase (tagged with the caller's `user_id`)
    once streaming finishes, purely so the frontend can render the log.

    `payload.thread_id` is authorized (fail-closed, see `_authorize_thread`)
    *before* the graph is touched or the response is constructed, so an
    unowned/nonexistent thread never reaches the checkpointer or the LLM.
    """
    request_id = str(uuid.uuid4())

    api_keys, default_model, profile_codeforces_handle = await _resolve_byok_profile(user.user_id)
    codeforces_handle = payload.codeforces_handle or profile_codeforces_handle

    await _authorize_thread(payload.thread_id, user.user_id)

    return StreamingResponse(
        agent_chat_stream(
            payload.message,
            api_keys,
            default_model,
            codeforces_handle,
            payload.thread_id,
            user.user_id,
            request_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-Id": request_id,
        },
    )


@router.get("/chat/history/{thread_id}")
async def chat_history(thread_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    """Returns prior messages for `thread_id`, oldest first, from the
    Supabase message log (UI rendering only — see module docstring; this is
    not the agent's own checkpointed memory).

    Used by the frontend to rehydrate a chat thread (e.g. after a page
    refresh or when switching sessions in the sidebar). Requires a valid
    Supabase session and 403s if `thread_id` belongs to someone else.
    """
    await _authorize_thread(thread_id, user.user_id)
    messages = await get_db_service().get_chat_history(thread_id)
    return {"messages": messages}
