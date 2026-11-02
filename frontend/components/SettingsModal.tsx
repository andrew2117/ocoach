"use client";

import { Loader2, LogOut, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { getProfile, saveProfile } from "@/lib/api";
import { useLanguage, type TranslationKey } from "@/lib/LanguageContext";
import {
  DEFAULT_MODEL_ID,
  canonicalModelId,
  PROVIDER_LABELS,
  type ModelProvider,
  modelsByProvider,
  providerForModel,
} from "@/lib/models";

type SettingsModalProps = {
  onClose: () => void;
  onSaved?: () => void;
};

/** New (not-yet-saved) key text the user has typed for each provider. Kept
 * independently per provider so switching the model dropdown back and
 * forth never discards what was typed into a field that's currently
 * hidden — see the module-level note in `handleSave` for why *all three*
 * are sent on every save, not just the one for the selected model.
 */
type ApiKeyInputs = Record<ModelProvider, string>;

type SavedKeyState = Record<ModelProvider, { has: boolean; preview: string | null }>;

const EMPTY_INPUTS: ApiKeyInputs = { anthropic: "", openai: "", google: "" };
const EMPTY_SAVED: SavedKeyState = {
  anthropic: { has: false, preview: null },
  openai: { has: false, preview: null },
  google: { has: false, preview: null },
};

type SaveProfilePayload = {
  codeforcesHandle: string;
  defaultModel: string;
  apiKeyInputs: ApiKeyInputs;
  savedKeys: SavedKeyState;
};

type SaveProfileState = {
  generalError: string | null;
  apiKeyError: string | null;
  apiKeyErrorKey: TranslationKey | null;
  apiKeyErrorParams: Record<string, string> | null;
  successKey: TranslationKey | null;
  profile: {
    codeforcesHandle: string;
    defaultModel: string;
    savedKeys: SavedKeyState;
  } | null;
};

const initialSaveState: SaveProfileState = {
  generalError: null,
  apiKeyError: null,
  apiKeyErrorKey: null,
  apiKeyErrorParams: null,
  successKey: null,
  profile: null,
};

function isApiKeyFieldError(message: string): boolean {
  const lower = message.toLowerCase();
  return (
    lower.includes("anthropic") ||
    lower.includes("openai") ||
    lower.includes("google") ||
    lower.includes("gemini") ||
    lower.includes("api key") ||
    lower.includes("sk-ant") ||
    lower.includes("model")
  );
}

const KEY_PREFIX_BY_PROVIDER: Record<ModelProvider, { prefix: string; errorKey: TranslationKey }> = {
  anthropic: { prefix: "sk-ant-", errorKey: "settings.invalidKeyPrefixAnthropic" },
  openai: { prefix: "sk-", errorKey: "settings.invalidKeyPrefixOpenai" },
  google: { prefix: "AQ.", errorKey: "settings.invalidKeyPrefixGoogle" },
};

function validateApiKey(provider: ModelProvider, key: string): TranslationKey | null {
  if (!key) return null;
  const { prefix, errorKey } = KEY_PREFIX_BY_PROVIDER[provider];
  if (!key.startsWith(prefix)) {
    return errorKey;
  }
  if (key.length < 20) {
    return "settings.invalidKeyLength";
  }
  return null;
}

async function saveProfileAction(
  _prev: SaveProfileState,
  payload: SaveProfilePayload,
): Promise<SaveProfileState> {
  const trimmedHandle = payload.codeforcesHandle.trim() || null;
  const trimmedKeys: ApiKeyInputs = {
    anthropic: payload.apiKeyInputs.anthropic.trim(),
    openai: payload.apiKeyInputs.openai.trim(),
    google: payload.apiKeyInputs.google.trim(),
  };

  const selectedProvider = providerForModel(payload.defaultModel);
  const hasExistingForSelected = payload.savedKeys[selectedProvider].has;
  const newKeyForSelected = trimmedKeys[selectedProvider];

  if (!newKeyForSelected && !hasExistingForSelected) {
    return {
      generalError: null,
      apiKeyError: null,
      apiKeyErrorKey: "settings.apiKeyRequired",
      apiKeyErrorParams: { provider: PROVIDER_LABELS[selectedProvider] },
      successKey: null,
      profile: null,
    };
  }

  if (newKeyForSelected) {
    const keyValidationError = validateApiKey(selectedProvider, newKeyForSelected);
    if (keyValidationError) {
      return {
        generalError: null,
        apiKeyError: null,
        apiKeyErrorKey: keyValidationError,
        apiKeyErrorParams: null,
        successKey: null,
        profile: null,
      };
    }
  }

  try {
    // All three keys are sent (as `null` when nothing new was typed for
    // that provider) rather than just the selected one — the backend only
    // overwrites a provider's stored key when a non-null value is sent
    // (see `backend/services/profiles.py::upsert_profile`), so this lets a
    // user type an OpenAI key, switch the dropdown to a Gemini model, and
    // still have that OpenAI key persisted on the same save.
    const profile = await saveProfile({
      codeforces_handle: trimmedHandle,
      default_model: payload.defaultModel,
      anthropic_api_key: trimmedKeys.anthropic || null,
      openai_api_key: trimmedKeys.openai || null,
      google_api_key: trimmedKeys.google || null,
    });

    return {
      generalError: null,
      apiKeyError: null,
      apiKeyErrorKey: null,
      apiKeyErrorParams: null,
      successKey: "settings.profileSaved",
      profile: {
        codeforcesHandle: profile.codeforces_handle ?? "",
        defaultModel: profile.default_model,
        savedKeys: {
          anthropic: { has: profile.has_anthropic_api_key, preview: profile.anthropic_api_key_preview },
          openai: { has: profile.has_openai_api_key, preview: profile.openai_api_key_preview },
          google: { has: profile.has_google_api_key, preview: profile.google_api_key_preview },
        },
      },
    };
  } catch (err) {
    const message = (err as Error).message;
    if (isApiKeyFieldError(message)) {
      return {
        generalError: null,
        apiKeyError: message,
        apiKeyErrorKey: null,
        apiKeyErrorParams: null,
        successKey: null,
        profile: null,
      };
    }
    return {
      generalError: message,
      apiKeyError: null,
      apiKeyErrorKey: null,
      apiKeyErrorParams: null,
      successKey: null,
      profile: null,
    };
  }
}

export default function SettingsModal({ onClose, onSaved }: SettingsModalProps) {
  const { t } = useLanguage();
  const [codeforcesHandle, setCodeforcesHandle] = useState("");
  const [defaultModel, setDefaultModel] = useState(DEFAULT_MODEL_ID);
  const [apiKeyInputs, setApiKeyInputs] = useState<ApiKeyInputs>(EMPTY_INPUTS);
  const [savedKeys, setSavedKeys] = useState<SavedKeyState>(EMPTY_SAVED);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveProfileState>(initialSaveState);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      setLoading(true);
      setLoadError(null);
      try {
        const profile = await getProfile();
        if (cancelled) return;

        setCodeforcesHandle(profile.codeforces_handle ?? "");
        setDefaultModel(canonicalModelId(profile.default_model));
        setSavedKeys({
          anthropic: { has: profile.has_anthropic_api_key, preview: profile.anthropic_api_key_preview },
          openai: { has: profile.has_openai_api_key, preview: profile.openai_api_key_preview },
          google: { has: profile.has_google_api_key, preview: profile.google_api_key_preview },
        });
      } catch (err) {
        if (!cancelled) setLoadError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadProfile();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSave() {
    setIsSaving(true);
    try {
      // Called directly from this event handler (not mirrored in via a
      // `useEffect` keyed on some prior result) so the follow-up state
      // updates below run exactly once, synchronously with the user's
      // save action rather than as a derived-state effect.
      const result = await saveProfileAction(saveState, {
        codeforcesHandle,
        defaultModel,
        apiKeyInputs,
        savedKeys,
      });
      setSaveState(result);
      if (result.profile) {
        setSavedKeys(result.profile.savedKeys);
        setCodeforcesHandle(result.profile.codeforcesHandle);
        setDefaultModel(result.profile.defaultModel);
        setApiKeyInputs(EMPTY_INPUTS);
        onSaved?.();
      }
    } finally {
      setIsSaving(false);
    }
  }

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    window.location.href = "/login";
  }

  const selectedProvider = providerForModel(defaultModel);
  const selectedProviderSaved = savedKeys[selectedProvider];
  const selectedProviderInput = apiKeyInputs[selectedProvider];

  const apiKeyLabelKey: TranslationKey =
    selectedProvider === "anthropic"
      ? "settings.anthropicApiKey"
      : selectedProvider === "openai"
        ? "settings.openaiApiKey"
        : "settings.googleApiKey";

  const newKeyPlaceholderKey: TranslationKey =
    selectedProvider === "anthropic"
      ? "settings.keyPlaceholderNewAnthropic"
      : selectedProvider === "openai"
        ? "settings.keyPlaceholderNewOpenai"
        : "settings.keyPlaceholderNewGoogle";

  const apiKeyErrorMessage =
    saveState.apiKeyError ??
    (saveState.apiKeyErrorKey
      ? t(saveState.apiKeyErrorKey, saveState.apiKeyErrorParams ?? undefined)
      : null);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm transition-opacity p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-xl max-w-md w-full p-6 space-y-5 rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
            {t("settings.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
            aria-label={t("settings.closeSettings")}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-700/60 rounded-xl p-3 text-xs text-zinc-600 dark:text-zinc-400 flex items-start gap-2.5">
          <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
          <p>{t("settings.securityNotice")}</p>
        </div>

        {loading ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {t("settings.loadingProfile")}
          </p>
        ) : (
          <div className="space-y-4">
            <div>
              <label
                htmlFor="codeforces-handle"
                className="text-xs font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1.5 block"
              >
                {t("settings.codeforcesHandle")}
              </label>
              <input
                id="codeforces-handle"
                value={codeforcesHandle}
                onChange={(e) => setCodeforcesHandle(e.target.value)}
                placeholder={t("settings.codeforcesPlaceholder")}
                className="w-full px-3.5 py-2 rounded-lg text-sm bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100 transition-all"
              />
            </div>

            <div>
              <label
                htmlFor="active-model"
                className="text-xs font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1.5 block"
              >
                {t("settings.selectModel")}
              </label>
              <select
                id="active-model"
                value={defaultModel}
                onChange={(e) => setDefaultModel(e.target.value)}
                className="w-full px-3.5 py-2 rounded-lg text-sm bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100 transition-all"
              >
                {modelsByProvider().map((group) => (
                  <optgroup key={group.provider} label={PROVIDER_LABELS[group.provider]}>
                    {group.options.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>

            <div>
              <label
                htmlFor="provider-api-key"
                className="text-xs font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1.5 block"
              >
                {t(apiKeyLabelKey)}
              </label>
              <input
                id="provider-api-key"
                type="password"
                value={selectedProviderInput}
                onChange={(e) =>
                  setApiKeyInputs((prev) => ({ ...prev, [selectedProvider]: e.target.value }))
                }
                placeholder={
                  selectedProviderSaved.has
                    ? t("settings.keyPlaceholderSaved", {
                        preview: selectedProviderSaved.preview ?? t("settings.hidden"),
                      })
                    : t(newKeyPlaceholderKey)
                }
                aria-invalid={apiKeyErrorMessage ? true : undefined}
                className={`w-full px-3.5 py-2 rounded-lg text-sm bg-white dark:bg-zinc-800 border text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100 transition-all ${
                  apiKeyErrorMessage
                    ? "border-red-400 dark:border-red-500 focus:ring-red-500 dark:focus:ring-red-400"
                    : "border-zinc-300 dark:border-zinc-700"
                }`}
                autoComplete="off"
              />
              <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                {selectedProviderSaved.has
                  ? t("settings.keySavedHint")
                  : t("settings.keyNotSavedHint")}
              </p>
              {apiKeyErrorMessage && (
                <p className="mt-1.5 text-xs text-red-600 dark:text-red-400" role="alert">
                  {apiKeyErrorMessage}
                </p>
              )}
            </div>
          </div>
        )}

        {loadError && (
          <p className="text-xs text-red-600 dark:text-red-400">{loadError}</p>
        )}
        {saveState.generalError && (
          <p className="text-xs text-red-600 dark:text-red-400">
            {saveState.generalError}
          </p>
        )}
        {saveState.successKey && (
          <p className="text-xs text-green-700 dark:text-green-400">
            {t(saveState.successKey)}
          </p>
        )}

        <div className="border-t border-zinc-200 dark:border-zinc-800 pt-4 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={handleSignOut}
            className="text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 px-2.5 py-1.5 rounded-md flex items-center gap-1.5 transition-colors"
          >
            <LogOut className="h-3.5 w-3.5" />
            {t("settings.signOut")}
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium rounded-lg border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 transition-colors"
            >
              {t("settings.cancel")}
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={loading || isSaving}
              className="inline-flex items-center justify-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200 transition-colors disabled:opacity-50"
            >
              {isSaving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {isSaving ? t("settings.saving") : t("settings.save")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
