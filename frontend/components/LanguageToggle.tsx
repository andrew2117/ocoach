"use client";

import { Globe } from "lucide-react";
import { useEffect, useState } from "react";
import { useLanguage } from "@/lib/LanguageContext";

export default function LanguageToggle() {
  const { language, toggleLanguage, t } = useLanguage();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div
        className="h-8 w-8 rounded-lg bg-zinc-100 dark:bg-zinc-800"
        aria-hidden
      />
    );
  }

  const label = language.toUpperCase();

  return (
    <button
      type="button"
      onClick={toggleLanguage}
      className="inline-flex items-center justify-center gap-1 h-8 min-w-8 px-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-500 transition-all duration-150"
      title={t("language.toggle")}
      aria-label={t("language.toggle")}
    >
      <Globe className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="text-xs font-semibold tracking-wide">{label}</span>
    </button>
  );
}
