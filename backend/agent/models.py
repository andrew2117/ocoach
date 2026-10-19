"""Multi-provider BYOK model catalog.

Single source of truth for which chat-completion models the coach supports,
which provider each belongs to, and which `profiles` column/`api_keys` dict
key holds the BYOK credential for that provider.

`frontend/lib/models.ts` mirrors this catalog's `id`/`provider`/`label`
triples for the Settings model selector — keep the two in sync by hand when
adding/removing a model (there's no cross-language codegen here, so this
module's `MODEL_CATALOG` is the canonical list; the frontend one must match
it exactly for every `id`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ModelProvider(str, Enum):
    """A BYOK provider. The string value doubles as:
    - the key under `profiles.api_keys`/`UserProfile.api_keys` (and the
      `{provider}_api_key` column name on `public.profiles`), and
    - the `configurable.api_keys` dict key threaded into the agent graph
      (see `agent/graph.py::_resolve_llm`).
    """

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"


@dataclass(frozen=True)
class ModelOption:
    id: str
    provider: ModelProvider
    label: str


# Ordered for display: grouped by provider, cheapest/fastest-to-most-capable
# within a provider isn't enforced here — just a stable, sensible order.
MODEL_CATALOG: tuple[ModelOption, ...] = (
    ModelOption("claude-sonnet-5", ModelProvider.ANTHROPIC, "Claude Sonnet 5"),
    ModelOption("claude-opus-5", ModelProvider.ANTHROPIC, "Claude Opus 5"),
    ModelOption("claude-haiku-4-5", ModelProvider.ANTHROPIC, "Claude Haiku 4.5"),
    ModelOption("gpt-4o", ModelProvider.OPENAI, "GPT-4o"),
    ModelOption("gpt-4o-mini", ModelProvider.OPENAI, "GPT-4o mini"),
    ModelOption("gpt-4.1", ModelProvider.OPENAI, "GPT-4.1"),
    ModelOption("gemini-1.5-pro", ModelProvider.GOOGLE, "Gemini 1.5 Pro"),
    ModelOption("gemini-1.5-flash", ModelProvider.GOOGLE, "Gemini 1.5 Flash"),
)

MODEL_BY_ID: dict[str, ModelOption] = {option.id: option for option in MODEL_CATALOG}

# Catalog ids that were offered before they existed on the provider.
# Anthropic 404s `claude-haiku-5`; Haiku 4.5 (`claude-haiku-4-5`) is the
# current fast model. Profiles saved with the old id keep working.
_RETIRED_MODEL_IDS: dict[str, str] = {
    "claude-haiku-5": "claude-haiku-4-5",
}

# Used as the implicit choice for brand-new profiles (see the
# `upsert_user_profile` RPC's `default_model` default and
# `services/profiles.py`) and as the fallback if a caller's stored
# `default_model` somehow doesn't match any known id (defensive only --
# `routes/profile.py` validates against `MODEL_BY_ID` on every write).
DEFAULT_MODEL_ID = "claude-sonnet-5"


class UnknownModelError(ValueError):
    """Raised when a `model_id` doesn't match any entry in `MODEL_CATALOG`."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        super().__init__(f"Unknown model: {model_id!r}")


class MissingProviderKeyError(RuntimeError):
    """Raised when the provider required by the selected model has no BYOK
    key saved for the current user.

    Carries the resolved `ModelOption` (not just the provider) so callers
    (see `services/agent.py`) can build a message that names the specific
    model the user picked, not just the provider.
    """

    def __init__(self, model: ModelOption) -> None:
        self.model = model
        super().__init__(
            f"No {model.provider.value} API key is configured for model '{model.id}'."
        )


def canonicalize_model_id(model_id: str | None) -> str | None:
    """Rewrites a known retired catalog id to its replacement.

    Empty values pass through unchanged so callers can still distinguish
    "not provided" from a real selection. Unknown ids are left alone;
    `resolve_model` is what rejects those.
    """
    if not model_id:
        return model_id
    return _RETIRED_MODEL_IDS.get(model_id, model_id)


def resolve_model(model_id: str | None) -> ModelOption:
    """Looks up `model_id` in `MODEL_CATALOG`, falling back to
    `DEFAULT_MODEL_ID` when `model_id` is falsy (e.g. an old profile row
    saved before `default_model` existed).

    Raises `UnknownModelError` for a non-empty but unrecognized id, rather
    than silently falling back — a stale/typo'd model id should surface as
    a clear error, not silently reroute the user to a different provider's
    model than the one they explicitly selected in Settings. The one
    exception is `_RETIRED_MODEL_IDS`: ids this app itself used to offer
    that the provider rejects.
    """
    effective_id = canonicalize_model_id(model_id) or DEFAULT_MODEL_ID
    option = MODEL_BY_ID.get(effective_id)
    if option is None:
        raise UnknownModelError(effective_id)
    return option


def models_by_provider() -> dict[ModelProvider, list[ModelOption]]:
    """Groups `MODEL_CATALOG` by provider, preserving catalog order within
    each group. Used by nothing server-side today (the frontend keeps its
    own grouped view), but kept here as the canonical grouping helper so
    any future server-side consumer (e.g. a `GET /api/models` endpoint)
    doesn't need to reimplement it.
    """
    grouped: dict[ModelProvider, list[ModelOption]] = {}
    for option in MODEL_CATALOG:
        grouped.setdefault(option.provider, []).append(option)
    return grouped
