"""Pydantic request/response models for the /api/sessions endpoints
(Phase 5: multi-session chat UI)."""

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """Optional body payload for POST /api/sessions."""

    title: str | None = Field(
        default=None,
        max_length=200,
        description="Display title for the new session. Defaults to 'New chat'.",
    )


class UpdateSessionRequest(BaseModel):
    """Body payload for PATCH /api/sessions/{session_id}."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="New display title for the session.",
    )


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str | None = None
