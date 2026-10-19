"""Pydantic request/response models for the /api/profile endpoints."""

from pydantic import BaseModel, Field

from agent.models import DEFAULT_MODEL_ID


class UpdateProfileRequest(BaseModel):
    """Body payload for POST /api/profile.

    Every field is optional and `None`/omitted means "leave the existing
    stored value unchanged" (see `services/profiles.py::upsert_profile`),
    *except* `codeforces_handle`, which is always overwritten (including to
    clear it) — same semantics the single-provider version of this
    endpoint had. This lets Settings save just the field the user actually
    changed (e.g. only a newly-typed OpenAI key) without having to resend
    every other provider's key.
    """

    codeforces_handle: str | None = Field(
        default=None,
        max_length=100,
        description="The user's Codeforces handle, or null to clear it.",
    )
    anthropic_api_key: str | None = Field(
        default=None,
        description=(
            "Plaintext Anthropic API key to encrypt and store. Omit or pass "
            "null to leave an existing saved key unchanged."
        ),
    )
    openai_api_key: str | None = Field(
        default=None,
        description=(
            "Plaintext OpenAI API key to encrypt and store. Omit or pass "
            "null to leave an existing saved key unchanged."
        ),
    )
    google_api_key: str | None = Field(
        default=None,
        description=(
            "Plaintext Google (Gemini) API key to encrypt and store. Omit or pass "
            "null to leave an existing saved key unchanged."
        ),
    )
    default_model: str | None = Field(
        default=None,
        description=(
            "Model id to use for this user's chats (see GET /api/profile's "
            "`available_models`), e.g. 'claude-sonnet-5', 'gpt-4o', or "
            "'gemini-1.5-pro'. Omit or pass null to leave the existing "
            "preference unchanged; defaults to "
            f"{DEFAULT_MODEL_ID!r} for a brand-new profile."
        ),
    )


class ModelOptionResponse(BaseModel):
    """One selectable entry for the Settings model dropdown."""

    id: str
    provider: str
    label: str


class ProfileResponse(BaseModel):
    codeforces_handle: str | None
    default_model: str
    available_models: list[ModelOptionResponse] = Field(
        description="The full model catalog, grouped client-side by `provider`.",
    )

    has_anthropic_api_key: bool
    anthropic_api_key_preview: str | None = Field(
        default=None,
        description=(
            "Masked preview of the stored Anthropic key (e.g. 'sk-ant-***abcd'), "
            "safe to render in Settings. Never the raw decrypted secret — see "
            "routes/profile.py::_mask_api_key. Null when no key is stored."
        ),
    )

    has_openai_api_key: bool
    openai_api_key_preview: str | None = Field(
        default=None,
        description="Masked preview of the stored OpenAI key, or null when none is stored.",
    )

    has_google_api_key: bool
    google_api_key_preview: str | None = Field(
        default=None,
        description="Masked preview of the stored Google (Gemini) key, or null when none is stored.",
    )
