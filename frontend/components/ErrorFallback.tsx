"use client";

type ErrorFallbackProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function ErrorFallback({ error, reset }: ErrorFallbackProps) {
  const isDev = process.env.NODE_ENV === "development";

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 p-6 text-center">
      <div className="max-w-md rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
        <h2 className="text-lg font-semibold text-gray-900">
          Something went wrong
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          An unexpected error occurred. You can try again, or refresh the page
          if the problem persists.
        </p>
        {isDev && error.message && (
          <p className="mt-3 rounded bg-gray-100 px-3 py-2 text-left text-xs font-mono text-gray-700 break-all">
            {error.message}
          </p>
        )}
        <button
          type="button"
          onClick={reset}
          className="mt-6 rounded bg-black px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
