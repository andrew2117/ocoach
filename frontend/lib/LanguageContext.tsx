"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { dictionaries, type Dictionary, type EnglishDictionary, type Locale } from "@/locales";

const STORAGE_KEY = "ocoach-language";

type TranslationKey = {
  [Section in keyof EnglishDictionary & string]: {
    [Key in keyof EnglishDictionary[Section] & string]: EnglishDictionary[Section][Key] extends string
      ? `${Section}.${Key}`
      : EnglishDictionary[Section][Key] extends Record<string, unknown>
        ? {
            [NestedKey in keyof EnglishDictionary[Section][Key] & string]: `${Section}.${Key}.${NestedKey}`;
          }[keyof EnglishDictionary[Section][Key] & string]
        : never;
  }[keyof EnglishDictionary[Section] & string];
}[keyof EnglishDictionary & string];

export type { TranslationKey };

type LanguageContextValue = {
  language: Locale;
  setLanguage: (locale: Locale) => void;
  toggleLanguage: () => void;
  t: (key: TranslationKey, params?: Record<string, string>) => string;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

function getNestedValue(
  dict: Dictionary,
  key: TranslationKey,
): string | undefined {
  const parts = key.split(".");
  let current: unknown = dict;

  for (const part of parts) {
    if (current == null || typeof current !== "object" || !(part in current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[part];
  }

  return typeof current === "string" ? current : undefined;
}

function interpolate(
  template: string,
  params?: Record<string, string>,
): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, name: string) => params[name] ?? `{${name}}`);
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Locale>("en");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "en" || stored === "es") {
      setLanguageState(stored);
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    localStorage.setItem(STORAGE_KEY, language);
    document.documentElement.lang = language;
  }, [language, hydrated]);

  const setLanguage = useCallback((locale: Locale) => {
    setLanguageState(locale);
  }, []);

  const toggleLanguage = useCallback(() => {
    setLanguageState((prev) => (prev === "en" ? "es" : "en"));
  }, []);

  const t = useCallback(
    (key: TranslationKey, params?: Record<string, string>) => {
      const value =
        getNestedValue(dictionaries[language], key) ??
        getNestedValue(dictionaries.en, key) ??
        key;
      return interpolate(value, params);
    },
    [language],
  );

  const value = useMemo(
    () => ({ language, setLanguage, toggleLanguage, t }),
    [language, setLanguage, toggleLanguage, t],
  );

  return (
    <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
  );
}

export function useLanguage(): LanguageContextValue {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }
  return context;
}
