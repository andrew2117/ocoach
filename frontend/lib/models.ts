/**
 * Multi-provider BYOK model catalog.
 *
 * Mirrors `backend/agent/models.py::MODEL_CATALOG` — every `id` here must
 * match an id there exactly (there's no cross-language codegen; keep the
 * two in sync by hand when adding/removing a model). The backend is the
 * source of truth for *which* ids are valid (it rejects an unrecognized
 * `default_model` on `POST /api/profile`); this file only adds display
 * labels/grouping for the Settings UI.
 */

export type ModelProvider = "anthropic" | "openai" | "google";

export type ModelOption = {
  id: string;
  provider: ModelProvider;
  label: string;
};

export const MODEL_CATALOG: readonly ModelOption[] = [
  { id: "claude-sonnet-5", provider: "anthropic", label: "Claude Sonnet 5" },
  { id: "claude-opus-5", provider: "anthropic", label: "Claude Opus 5" },
  { id: "claude-haiku-4-5", provider: "anthropic", label: "Claude Haiku 4.5" },
  { id: "gpt-4o", provider: "openai", label: "GPT-4o" },
  { id: "gpt-4o-mini", provider: "openai", label: "GPT-4o mini" },
  { id: "gpt-4.1", provider: "openai", label: "GPT-4.1" },
  { id: "gemini-4-argon", provider: "google", label: "Gemini 4" },
  { id: "gemini-3.8-flash", provider: "google", label: "Gemini 3.8 Flash" },
  { id: "gemini-3.5-flash-lite", provider: "google", label: "Gemini 3.5 Flash Lite" },
] as const;

export const DEFAULT_MODEL_ID = "claude-sonnet-5";

/**
 * Ids this app used to offer that the provider no longer serves. Google's
 * lineup retires on a published schedule (see
 * https://ai.google.dev/gemini-api/docs/models#model-versions) — every
 * `gemini-*` id this app has ever offered is listed here so a profile saved
 * years ago still resolves to a current model.
 */
const RETIRED_MODEL_IDS: Readonly<Record<string, string>> = {
  "claude-haiku-5": "claude-haiku-4-5",
  "gemini-1.5-pro": "gemini-4-argon",
  "gemini-1.5-flash": "gemini-3.8-flash",
  "gemini-1.5-pro-002": "gemini-4-argon",
  "gemini-1.5-flash-002": "gemini-3.8-flash",
  "gemini-2.5-pro": "gemini-4-argon",
  "gemini-2.5-flash": "gemini-3.8-flash",
  "gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
};

/** Rewrites a retired catalog id so a saved preference still matches an option. */
export function canonicalModelId(modelId: string | null | undefined): string {
  if (!modelId) return DEFAULT_MODEL_ID;
  return RETIRED_MODEL_IDS[modelId] ?? modelId;
}

export const MODEL_BY_ID: ReadonlyMap<string, ModelOption> = new Map(
  MODEL_CATALOG.map((option) => [option.id, option]),
);

export const PROVIDER_ORDER: readonly ModelProvider[] = [
  "anthropic",
  "openai",
  "google",
];

export const PROVIDER_LABELS: Record<ModelProvider, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google Gemini",
};

/** Groups `MODEL_CATALOG` by provider, in `PROVIDER_ORDER`, for rendering
 * `<optgroup>`s in the Settings model `<select>`.
 */
export function modelsByProvider(): Array<{
  provider: ModelProvider;
  options: ModelOption[];
}> {
  return PROVIDER_ORDER.map((provider) => ({
    provider,
    options: MODEL_CATALOG.filter((option) => option.provider === provider),
  })).filter((group) => group.options.length > 0);
}

/** Looks up `modelId`'s provider, defaulting to `"anthropic"` (matching
 * `DEFAULT_MODEL_ID`'s provider) if `modelId` is unrecognized — purely a
 * display fallback; the backend is the actual source of truth and will
 * reject an unknown id on save.
 */
export function providerForModel(modelId: string): ModelProvider {
  return MODEL_BY_ID.get(modelId)?.provider ?? "anthropic";
}
