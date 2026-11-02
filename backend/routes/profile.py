"""Profile routes: read/write BYOK settings for the signed-in user.

Writes go through the `upsert_user_profile` RPC with Fernet-encrypted API keys
(application-level encryption — hosted Supabase blocks pgsodium encrypt in SQL).
The frontend never performs encrypted writes directly — it POSTs here with the
user's session token, and this route scopes the upsert to `user.user_id` from
JWT verification.

Phase 7: `public.profiles` no longer grants `authenticated`/`anon` any
direct privileges at all (see the Phase 7 RLS-lockdown migration) — a
client could otherwise `UPDATE` the ciphertext column with a plaintext
value, silently bypassing Fernet encryption entirely, or `SELECT` the raw
ciphertext for no real benefit. This module is now the *only* way the
frontend can read or write profile state: `GET` below replaces the
frontend's former direct PostgREST read (`SettingsModal.tsx`), and `POST`
remains the only write path (via the `upsert_user_profile` RPC, run with
the backend's service role).

Phase 11: multi-provider BYOK. `profiles` now holds one key per provider
(Anthropic/OpenAI/Google) plus a `default_model` preference (see
`agent/models.py` for the catalog and `services/profiles.py` for storage).
`GET` also returns the full model catalog (`available_models`) so the
frontend's Settings dropdown doesn't need its own hardcoded copy of model
ids — only display grouping/labels live in `frontend/lib/models.ts`, which
must still list the same ids as `agent/models.py::MODEL_CATALOG`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from agent.models import DEFAULT_MODEL_ID, MODEL_BY_ID, MODEL_CATALOG, canonicalize_model_id
from core.security import AuthenticatedUser, get_current_user
from models.profile import ModelOptionResponse, ProfileResponse, UpdateProfileRequest
from services.profiles import UserProfile, get_profile_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile"])

# API keys across all three providers start with a recognizable prefix
# (Anthropic: "sk-ant-...", OpenAI: "sk-...", Gemini auth keys: "AQ....").
# Gemini standard keys ("AIza...") are deprecated; AI Studio now issues
# authorization keys bound to a service account. Keeping a short,
# fixed-length prefix + a short suffix is enough for a user to recognize
# "yes, that's the key I saved" without reconstructing anything usable —
# this is a UI affordance, not a secret, and must never be treated as one.
_GEMINI_AUTH_KEY_PREFIX = "AQ."
_PREVIEW_PREFIX_CHARS = 7
_PREVIEW_SUFFIX_CHARS = 4

_AVAILABLE_MODELS = [
    ModelOptionResponse(id=option.id, provider=option.provider.value, label=option.label)
    for option in MODEL_CATALOG
]


def _mask_api_key(key: str) -> str:
    """Builds a display-safe preview of a decrypted API key.

    Deliberately lossy: only a short prefix/suffix survive, joined by a
    fixed `***` — never long enough for the two ends to leak meaningful
    entropy about the middle, and never the actual decrypted secret past
    this function's return value.
    """
    if len(key) <= _PREVIEW_PREFIX_CHARS + _PREVIEW_SUFFIX_CHARS:
        return f"{key[:_PREVIEW_PREFIX_CHARS]}***"
    return f"{key[:_PREVIEW_PREFIX_CHARS]}***{key[-_PREVIEW_SUFFIX_CHARS:]}"


def _to_response(profile: UserProfile | None, *, fallback_handle: str | None = None) -> ProfileResponse:
    """Shared `UserProfile` -> `ProfileResponse` mapping for both routes
    below, so the masking rule lives in exactly one place.
    """
    has_anthropic = bool(profile and profile.has_anthropic_key)
    has_openai = bool(profile and profile.has_openai_key)
    has_google = bool(profile and profile.has_google_key)

    default_model = DEFAULT_MODEL_ID
    if profile:
        default_model = canonicalize_model_id(profile.default_model) or DEFAULT_MODEL_ID

    return ProfileResponse(
        codeforces_handle=profile.codeforces_handle if profile else fallback_handle,
        default_model=default_model,
        available_models=_AVAILABLE_MODELS,
        has_anthropic_api_key=has_anthropic,
        anthropic_api_key_preview=_mask_api_key(profile.anthropic_api_key) if has_anthropic and profile else None,
        has_openai_api_key=has_openai,
        openai_api_key_preview=_mask_api_key(profile.openai_api_key) if has_openai and profile else None,
        has_google_api_key=has_google,
        google_api_key_preview=_mask_api_key(profile.google_api_key) if has_google and profile else None,
    )


@router.get("", response_model=ProfileResponse)
async def get_profile(user: AuthenticatedUser = Depends(get_current_user)):
    """Returns the caller's profile for the Settings UI.

    Never returns a raw decrypted key for any provider — only whether one
    is configured (`has_{provider}_api_key`) and a masked preview
    (`{provider}_api_key_preview`, see `_mask_api_key`). Backed by the
    service role via `services/profiles.py`, which is now the only reader
    of `public.profiles` at all (see module docstring).
    """
    profile_service = get_profile_service()
    if not profile_service.is_enabled:
        raise HTTPException(status_code=503, detail="Profile storage is not configured")

    profile = await profile_service.get_profile(user.user_id)
    return _to_response(profile)


@router.post("", response_model=ProfileResponse)
async def save_profile(
    payload: UpdateProfileRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Creates or updates the caller's profile row in `public.profiles`.

    Each provider key is independent: sending only `openai_api_key` leaves
    any previously-saved Anthropic/Google key untouched (see
    `services/profiles.py::upsert_profile`). `default_model` must name a
    known model id (`agent/models.py::MODEL_CATALOG`) if provided.
    """
    profile_service = get_profile_service()
    if not profile_service.is_enabled:
        raise HTTPException(status_code=503, detail="Profile storage is not configured")

    trimmed_handle = payload.codeforces_handle.strip() if payload.codeforces_handle else None
    trimmed_handle = trimmed_handle or None

    trimmed_anthropic = payload.anthropic_api_key.strip() if payload.anthropic_api_key else None
    trimmed_anthropic = trimmed_anthropic or None

    trimmed_openai = payload.openai_api_key.strip() if payload.openai_api_key else None
    trimmed_openai = trimmed_openai or None

    trimmed_google = payload.google_api_key.strip() if payload.google_api_key else None
    trimmed_google = trimmed_google or None
    if trimmed_google is not None and not trimmed_google.startswith(_GEMINI_AUTH_KEY_PREFIX):
        raise HTTPException(
            status_code=400,
            detail='Invalid Gemini API key. Authorization keys start with "AQ.".',
        )

    trimmed_model = payload.default_model.strip() if payload.default_model else None
    trimmed_model = canonicalize_model_id(trimmed_model) or None
    if trimmed_model is not None and trimmed_model not in MODEL_BY_ID:
        raise HTTPException(status_code=400, detail=f"Unknown model: {trimmed_model!r}")

    existing = await profile_service.get_profile(user.user_id)
    has_existing_key = bool(existing and existing.has_any_api_key)
    has_new_key = bool(trimmed_anthropic or trimmed_openai or trimmed_google)
    if not has_existing_key and not has_new_key:
        raise HTTPException(
            status_code=400,
            detail="Add an API key for at least one provider before you can chat.",
        )

    try:
        await profile_service.upsert_profile(
            user.user_id,
            codeforces_handle=trimmed_handle,
            anthropic_api_key=trimmed_anthropic,
            openai_api_key=trimmed_openai,
            google_api_key=trimmed_google,
            default_model=trimmed_model,
        )
    except Exception:
        logger.exception("Failed to upsert profile for user_id=%s", user.user_id)
        raise HTTPException(status_code=503, detail="Could not save profile right now") from None

    updated = await profile_service.get_profile(user.user_id)
    return _to_response(updated, fallback_handle=trimmed_handle)
