"use client";

import ErrorFallback from "@/components/ErrorFallback";

type ErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function ChatError({ error, reset }: ErrorProps) {
  return <ErrorFallback error={error} reset={reset} />;
}
