"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import LanguageToggle from "@/components/LanguageToggle";
import ThemeToggle from "@/components/ThemeToggle";
import { createClient } from "@/lib/supabase/client";
import { useLanguage } from "@/lib/LanguageContext";

function GithubIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden
    >
      <path
        d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"
      />
    </svg>
  );
}

function LoginForm() {
  const { t } = useLanguage();
  const searchParams = useSearchParams();
  const authError = searchParams.get("error") === "auth";
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState<"github" | "magic" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function signInWithGitHub() {
    setLoading("github");
    setError(null);
    setMessage(null);

    const supabase = createClient();
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "github",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (oauthError) {
      setError(oauthError.message);
      setLoading(null);
    }
  }

  async function signInWithMagicLink(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) {
      setError(t("login.enterEmail"));
      return;
    }

    setLoading("magic");
    setError(null);
    setMessage(null);

    const supabase = createClient();
    const { error: otpError } = await supabase.auth.signInWithOtp({
      email: trimmed,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    setLoading(null);
    if (otpError) {
      setError(otpError.message);
      return;
    }
    setMessage(t("login.checkEmail"));
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-2">
      {/* Left — auth */}
      <div className="relative flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950 px-4 py-12">
        <div className="absolute top-4 right-4 z-50 flex items-center gap-2 rounded-lg bg-white/95 dark:bg-zinc-900/95 backdrop-blur-sm border border-zinc-300 dark:border-zinc-600 p-1 shadow-sm [&_button]:border-zinc-300 [&_button]:text-zinc-900 dark:[&_button]:border-zinc-600 dark:[&_button]:text-zinc-100 [&_button]:hover:bg-zinc-100 dark:[&_button]:hover:bg-zinc-800">
          <LanguageToggle />
          <ThemeToggle />
        </div>

        <div className="max-w-md w-full px-8 flex flex-col gap-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
              {t("login.title")}
            </h1>
            <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
              {t("login.subtitle")}
            </p>
          </div>

          <button
            type="button"
            onClick={signInWithGitHub}
            disabled={loading !== null}
            className="flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium bg-zinc-900 hover:bg-zinc-800 text-white dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200 transition-colors disabled:opacity-50"
          >
            <GithubIcon className="h-4 w-4" />
            {loading === "github"
              ? t("login.redirecting")
              : t("login.continueWithGitHub")}
          </button>

          <div className="flex items-center gap-3">
            <span className="flex-1 border-t border-zinc-200 dark:border-zinc-800" />
            <span className="text-zinc-600 dark:text-zinc-400 text-xs uppercase tracking-wide">
              {t("login.or")}
            </span>
            <span className="flex-1 border-t border-zinc-200 dark:border-zinc-800" />
          </div>

          <form onSubmit={signInWithMagicLink} className="flex flex-col gap-3">
            <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
              {t("login.emailMagicLink")}
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t("login.emailPlaceholder")}
                disabled={loading !== null}
                className="mt-1.5 w-full rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2.5 text-sm text-zinc-900 dark:text-zinc-100 shadow-sm placeholder:text-zinc-400 dark:placeholder:text-zinc-500 focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 dark:focus:border-zinc-400 dark:focus:ring-zinc-400 focus:outline-none transition-all duration-150 disabled:opacity-50"
              />
            </label>
            <button
              type="submit"
              disabled={loading !== null}
              className="w-full rounded-lg border border-zinc-300 dark:border-zinc-700 px-4 py-2.5 text-sm font-medium text-zinc-800 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50"
            >
              {loading === "magic"
                ? t("login.sending")
                : t("login.sendMagicLink")}
            </button>
          </form>

          {message && (
            <p className="text-xs text-green-700 dark:text-green-400">
              {message}
            </p>
          )}
          {authError && (
            <p className="text-xs text-red-600 dark:text-red-400">
              {t("login.signInFailed")}
            </p>
          )}
          {error && (
            <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
          )}
        </div>
      </div>

      {/* Right — brand / visual */}
      <div className="relative hidden lg:flex flex-col justify-center overflow-hidden bg-zinc-900 px-12 py-16">
        <div
          className="pointer-events-none absolute inset-0 opacity-30"
          aria-hidden
          style={{
            backgroundImage: `
              linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, transparent 50%),
              linear-gradient(225deg, rgba(6, 182, 212, 0.1) 0%, transparent 50%),
              repeating-linear-gradient(
                0deg,
                transparent,
                transparent 39px,
                rgba(255, 255, 255, 0.03) 39px,
                rgba(255, 255, 255, 0.03) 40px
              ),
              repeating-linear-gradient(
                90deg,
                transparent,
                transparent 39px,
                rgba(255, 255, 255, 0.03) 39px,
                rgba(255, 255, 255, 0.03) 40px
              )
            `,
          }}
        />

        <div className="relative z-10 max-w-lg">
          <p className="text-sm font-medium uppercase tracking-widest text-cyan-400/80 mb-4">
            {t("login.brandTagline")}
          </p>
          <h2 className="text-3xl font-semibold tracking-tight text-white mb-6">
            {t("login.brandHeadline1")}
            <br />
            {t("login.brandHeadline2")}
          </h2>

          <div className="rounded-xl border border-zinc-700/60 bg-zinc-950/60 backdrop-blur-sm p-5 font-mono text-sm leading-relaxed shadow-2xl">
            <div className="flex items-center gap-2 mb-3 text-zinc-500 text-xs">
              <span className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
              <span className="h-2.5 w-2.5 rounded-full bg-yellow-500/80" />
              <span className="h-2.5 w-2.5 rounded-full bg-green-500/80" />
              <span className="ml-2">solution.cpp</span>
            </div>
            <pre className="text-zinc-300 overflow-x-auto">
              <code>
                <span className="text-purple-400">#include</span>
                <span className="text-zinc-400"> &lt;bits/stdc++.h&gt;</span>
                {"\n"}
                <span className="text-purple-400">using namespace</span>
                <span className="text-cyan-300"> std</span>
                <span className="text-zinc-400">;</span>
                {"\n\n"}
                <span className="text-purple-400">int</span>
                <span className="text-yellow-300"> main</span>
                <span className="text-zinc-400">() {"{"}</span>
                {"\n"}
                <span className="text-zinc-500">{"    // OCoach: analyze weak tags,"}</span>
                {"\n"}
                <span className="text-zinc-500">{"    // drill problems, ace contests"}</span>
                {"\n"}
                <span className="text-purple-400">    return</span>
                <span className="text-orange-300"> 0</span>
                <span className="text-zinc-400">;</span>
                {"\n"}
                <span className="text-zinc-400">{"}"}</span>
              </code>
            </pre>
          </div>

          <p className="mt-8 text-sm text-zinc-400 leading-relaxed">
            {t("login.brandDescription")}
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
