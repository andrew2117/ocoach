"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

const THEMES = ["light", "dark", "system"] as const;
type ThemeOption = (typeof THEMES)[number];

function nextTheme(current: string | undefined): ThemeOption {
  const index = THEMES.indexOf((current ?? "system") as ThemeOption);
  const safeIndex = index === -1 ? 0 : index;
  return THEMES[(safeIndex + 1) % THEMES.length];
}

export default function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
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

  const isDark = resolvedTheme === "dark";
  const activeTheme = theme ?? "system";

  return (
    <button
      type="button"
      onClick={() => setTheme(nextTheme(theme))}
      className="inline-flex items-center justify-center h-8 w-8 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-all duration-150"
      title={`Theme: ${activeTheme}. Click to cycle.`}
      aria-label={`Theme: ${activeTheme}. Click to cycle between light, dark, and system.`}
    >
      {isDark ? (
        <Sun className="h-4 w-4" />
      ) : (
        <Moon className="h-4 w-4" />
      )}
    </button>
  );
}
