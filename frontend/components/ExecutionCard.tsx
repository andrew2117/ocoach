"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  HardDrive,
  Loader2,
  XCircle,
} from "lucide-react";
import type { CppExecutionResult } from "@/lib/api";

type ExecutionCardProps = {
  loading?: boolean;
  result?: CppExecutionResult;
};

const VERDICT_STYLES: Record<
  CppExecutionResult["verdict"],
  {
    border: string;
    accent: string;
    bg: string;
    text: string;
    icon: typeof CheckCircle2;
  }
> = {
  success: {
    border: "border-emerald-400",
    accent: "border-l-emerald-500",
    bg: "bg-emerald-50",
    text: "text-emerald-900",
    icon: CheckCircle2,
  },
  ce: {
    border: "border-red-400",
    accent: "border-l-red-500",
    bg: "bg-red-50",
    text: "text-red-900",
    icon: XCircle,
  },
  wa: {
    border: "border-red-400",
    accent: "border-l-red-500",
    bg: "bg-red-50",
    text: "text-red-900",
    icon: XCircle,
  },
  tle: {
    border: "border-amber-400",
    accent: "border-l-amber-500",
    bg: "bg-amber-50",
    text: "text-amber-900",
    icon: AlertTriangle,
  },
  re: {
    border: "border-red-400",
    accent: "border-l-red-500",
    bg: "bg-red-50",
    text: "text-red-900",
    icon: XCircle,
  },
  error: {
    border: "border-gray-400",
    accent: "border-l-gray-500",
    bg: "bg-gray-50",
    text: "text-gray-900",
    icon: AlertTriangle,
  },
};

function formatTime(seconds: number): string {
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)} ms`;
  }
  return `${seconds.toFixed(3)} s`;
}

function OutputSection({
  title,
  content,
}: {
  title: string;
  content: string | null | undefined;
}) {
  if (!content) return null;

  return (
    <details className="group rounded border border-gray-200 bg-white">
      <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50">
        {title}
      </summary>
      <pre className="max-h-48 overflow-auto border-t border-gray-200 px-3 py-2 text-xs text-gray-800 whitespace-pre-wrap font-mono">
        {content}
      </pre>
    </details>
  );
}

export default function ExecutionCard({ loading = false, result }: ExecutionCardProps) {
  if (loading) {
    return (
      <div className="rounded-lg border border-blue-300 border-l-4 border-l-blue-500 bg-blue-50 px-4 py-3 text-sm text-blue-950 shadow-sm">
        <div className="flex items-center gap-2 font-medium">
          <Loader2 className="h-4 w-4 animate-spin shrink-0" />
          <span>Compiling and running C++ on the server…</span>
        </div>
      </div>
    );
  }

  if (!result) return null;

  const style = VERDICT_STYLES[result.verdict] ?? VERDICT_STYLES.error;
  const Icon = style.icon;

  return (
    <div
      className={`rounded-lg border border-l-4 ${style.border} ${style.accent} ${style.bg} px-4 py-3 text-sm shadow-sm`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <Icon className={`h-5 w-5 mt-0.5 shrink-0 ${style.text}`} />
          <div className="min-w-0">
            <p className={`font-semibold ${style.text}`}>{result.status}</p>
            <p className="text-xs text-gray-600 mt-0.5">C++ execution</p>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5 shrink-0">
          {result.time != null && (
            <span className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] text-gray-700">
              <Clock className="h-3 w-3" />
              {formatTime(result.time)}
            </span>
          )}
          {result.memory != null && (
            <span className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] text-gray-700">
              <HardDrive className="h-3 w-3" />
              {result.memory} KB
            </span>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-col gap-2">
        <OutputSection title="Standard Output" content={result.stdout} />
        <OutputSection title="Standard Error" content={result.stderr} />
        <OutputSection title="Compile Output" content={result.compile_output} />
      </div>
    </div>
  );
}
