"use client";

import { AlertTriangle, CalendarClock, Loader2, Trophy } from "lucide-react";
import type { CodeforcesContestsResult, CodeforcesStatsResult } from "@/lib/api";

type CodeforcesStatsCardProps =
  | { kind: "stats"; loading?: boolean; result?: CodeforcesStatsResult }
  | { kind: "contests"; loading?: boolean; result?: CodeforcesContestsResult };

const LOADING_LABEL: Record<CodeforcesStatsCardProps["kind"], string> = {
  stats: "Analyzing Codeforces history…",
  contests: "Checking upcoming Codeforces contests…",
};

function ratingTier(rating: number | null): {
  label: string;
  badge: string;
} {
  if (rating == null)
    return {
      label: "Unrated",
      badge: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
    };
  if (rating >= 2400)
    return {
      label: "Grandmaster",
      badge: "bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-300",
    };
  if (rating >= 2100)
    return {
      label: "Master",
      badge: "bg-orange-100 text-orange-700 dark:bg-orange-950/50 dark:text-orange-300",
    };
  if (rating >= 1900)
    return {
      label: "Candidate Master",
      badge: "bg-purple-100 text-purple-700 dark:bg-purple-950/50 dark:text-purple-300",
    };
  if (rating >= 1600)
    return {
      label: "Expert",
      badge: "bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300",
    };
  if (rating >= 1400)
    return {
      label: "Specialist",
      badge: "bg-cyan-100 text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-300",
    };
  if (rating >= 1200)
    return {
      label: "Pupil",
      badge: "bg-green-100 text-green-700 dark:bg-green-950/50 dark:text-green-300",
    };
  return {
    label: "Newbie",
    badge: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
  };
}

function formatContestStart(iso: string | null): string {
  if (!iso) return "unknown start time";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 px-4 py-3 text-sm text-zinc-700 dark:text-zinc-300 shadow-sm">
      <div className="flex items-center gap-2 font-medium">
        <Loader2 className="h-4 w-4 animate-spin shrink-0" />
        <span>{label}</span>
      </div>
    </div>
  );
}

function ErrorState({ title, message }: { title: string; message: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 px-4 py-3 text-sm text-zinc-800 dark:text-zinc-200 shadow-sm">
      <div className="flex items-center gap-2 font-medium">
        <AlertTriangle className="h-4 w-4 shrink-0 text-zinc-500" />
        <span>{title}</span>
      </div>
      <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">{message}</p>
    </div>
  );
}

function StatsBody({ result }: { result: CodeforcesStatsResult }) {
  if (result.error) {
    return <ErrorState title="Codeforces stats unavailable" message={result.error} />;
  }

  const tier = ratingTier(result.rating);

  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-4 py-3 text-sm shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <Trophy className="h-5 w-5 mt-0.5 shrink-0 text-zinc-500 dark:text-zinc-400" />
          <div className="min-w-0">
            <p className="font-semibold text-zinc-900 dark:text-zinc-100">
              {result.handle}
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tier.badge}`}
              >
                {tier.label}
              </span>
              {result.rating != null && (
                <span className="text-xs font-mono text-zinc-600 dark:text-zinc-400">
                  {result.rating}
                  {result.max_rating != null && result.max_rating !== result.rating
                    ? ` (max ${result.max_rating})`
                    : ""}
                </span>
              )}
            </div>
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-2 py-0.5 text-[11px] text-zinc-600 dark:text-zinc-400">
          {result.submissions_analyzed} recent submission
          {result.submissions_analyzed === 1 ? "" : "s"}
        </span>
      </div>

      <div className="mt-3">
        {result.weak_tags.length === 0 ? (
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            No recurring WA/TLE weak spots detected — nice consistency.
          </p>
        ) : (
          <>
            <p className="mb-1.5 flex items-center gap-1 text-xs font-medium text-zinc-700 dark:text-zinc-300">
              <AlertTriangle className="h-3.5 w-3.5" />
              Weak topics (frequent WA/TLE)
            </p>
            <div className="flex flex-wrap gap-1.5">
              {result.weak_tags.map((t) => (
                <span
                  key={t.tag}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300"
                >
                  {t.tag}
                  <span className="text-zinc-400 dark:text-zinc-500">
                    ×{t.count}
                  </span>
                </span>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ContestsBody({ result }: { result: CodeforcesContestsResult }) {
  if (result.error) {
    return <ErrorState title="Contest schedule unavailable" message={result.error} />;
  }

  if (result.contests.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 px-4 py-3 text-sm text-zinc-700 dark:text-zinc-300 shadow-sm">
        No upcoming Codeforces contests were found.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-4 py-3 text-sm shadow-sm overflow-hidden">
      <div className="flex items-center gap-2 font-semibold text-zinc-900 dark:text-zinc-100 mb-3">
        <CalendarClock className="h-5 w-5 shrink-0 text-zinc-500 dark:text-zinc-400" />
        Upcoming Codeforces contests
      </div>
      <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-700">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-zinc-100 dark:bg-zinc-800">
              <th className="px-3 py-2 text-left text-xs font-semibold text-zinc-600 dark:text-zinc-400">
                Contest
              </th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-zinc-600 dark:text-zinc-400">
                Start
              </th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-zinc-600 dark:text-zinc-400">
                Duration
              </th>
            </tr>
          </thead>
          <tbody>
            {result.contests.map((c, i) => (
              <tr
                key={c.id ?? `${c.name}-${i}`}
                className="even:bg-zinc-50 dark:even:bg-zinc-800/40 border-t border-zinc-200 dark:border-zinc-700"
              >
                <td className="px-3 py-2 text-zinc-900 dark:text-zinc-100">
                  {c.name}
                </td>
                <td className="px-3 py-2 font-mono text-xs text-zinc-600 dark:text-zinc-400">
                  {formatContestStart(c.start_time_iso)}
                </td>
                <td className="px-3 py-2 font-mono text-xs text-zinc-600 dark:text-zinc-400">
                  {c.duration_hours}h
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function CodeforcesStatsCard(props: CodeforcesStatsCardProps) {
  const { kind, loading = false } = props;

  if (loading) return <LoadingState label={LOADING_LABEL[kind]} />;
  if (!props.result) return null;

  return kind === "stats" ? (
    <StatsBody result={props.result} />
  ) : (
    <ContestsBody result={props.result} />
  );
}
