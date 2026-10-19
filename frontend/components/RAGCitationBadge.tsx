"use client";

import { useState } from "react";
import { BookOpen, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import type { RagCitationsResult } from "@/lib/api";

type RAGCitationBadgeProps = {
  loading?: boolean;
  result?: RagCitationsResult;
};

function Pill({
  icon: Icon,
  children,
}: {
  icon: typeof BookOpen;
  children: React.ReactNode;
}) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full border border-gray-300 bg-gray-50 px-2.5 py-1 text-xs text-gray-600">
      <Icon className="h-3 w-3 shrink-0" />
      {children}
    </div>
  );
}

/** Collapsible by default: only the citation count pill renders until the
 * user opts in to see the underlying knowledge-base snippets. */
export default function RAGCitationBadge({
  loading = false,
  result,
}: RAGCitationBadgeProps) {
  const [expanded, setExpanded] = useState(false);

  if (loading) {
    return (
      <div className="inline-flex items-center gap-1.5 rounded-full border border-violet-300 bg-violet-50 px-2.5 py-1 text-xs text-violet-800">
        <Loader2 className="h-3 w-3 animate-spin shrink-0" />
        Searching the CP knowledge base…
      </div>
    );
  }

  if (!result) return null;

  if (result.error) {
    return <Pill icon={BookOpen}>Knowledge base unavailable</Pill>;
  }

  if (result.chunks.length === 0) {
    return <Pill icon={BookOpen}>No matching notes found</Pill>;
  }

  return (
    <div className="max-w-full">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="inline-flex items-center gap-1.5 rounded-full border border-violet-300 bg-violet-50 px-2.5 py-1 text-xs font-medium text-violet-800 hover:bg-violet-100"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0" />
        )}
        <BookOpen className="h-3 w-3 shrink-0" />
        {result.chunks.length} knowledge base citation
        {result.chunks.length === 1 ? "" : "s"}
      </button>

      {expanded && (
        <div className="mt-1.5 flex flex-col gap-1.5 rounded-lg border border-violet-200 bg-white p-2.5 shadow-sm">
          {result.chunks.map((chunk, i) => (
            <div
              key={`${chunk.source}-${i}`}
              className="rounded border border-violet-100 bg-violet-50/50 px-2.5 py-2 text-xs"
            >
              <div className="flex items-center justify-between gap-2 text-violet-700">
                <span className="font-medium truncate">{chunk.source}</span>
                {chunk.topic && (
                  <span className="shrink-0 rounded-full border border-violet-200 bg-white px-1.5 py-0.5 text-[10px]">
                    {chunk.topic}
                  </span>
                )}
              </div>
              <p className="mt-1 whitespace-pre-wrap text-gray-700">
                {chunk.snippet}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
