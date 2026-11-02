"""Pydantic request/response models for the chat endpoint."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Body payload for POST /api/chat.

    The caller's BYOK Anthropic API key is *not* accepted here (or anywhere
    else in the request) — the endpoint requires a Supabase session
    (`Authorization: Bearer <token>`, see `core/security.py`) and looks the
    key up server-side from the caller's encrypted `profiles` row
    (`services/profiles.py`).
    """

    message: str = Field(..., min_length=1, description="User's chat message")
    thread_id: str = Field(
        ...,
        description=(
            "Chat thread id (a UUID from POST /api/sessions). Scopes both the "
            "LangGraph agent's persistent memory (checkpointed per thread_id — "
            "see agent/graph.py) and the Supabase-backed message log used to "
            "render this thread in the UI. Callers must create a session first "
            "(POST /api/sessions) and pass its id here."
        ),
    )
    language: Literal["en", "es"] = Field(
        default="en",
        description=(
            "The UI language selected by the user. The agent replies strictly "
            "in this language, regardless of the language of the prompt."
        ),
    )
    codeforces_handle: str | None = Field(
        default=None,
        description=(
            "Optional Codeforces handle override for this request. When omitted, "
            "the handle saved in the caller's profile (if any) is used instead."
        ),
    )
