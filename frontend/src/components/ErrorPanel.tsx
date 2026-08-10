import { ApiError } from "../api/client";

// UI-7 requires ONE standard error component: human-readable message, correlation ID, retry.
// Every screen uses this rather than inventing its own error rendering.

interface Props {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}

export function ErrorPanel({ error, onRetry, title = "Something went wrong" }: Props) {
  const apiError = error instanceof ApiError ? error : null;
  const message =
    apiError?.message ?? (error instanceof Error ? error.message : "An unexpected error occurred.");

  return (
    <div role="alert" className="card border-red-300 p-4">
      <h2 className="text-sm font-semibold text-red-900">{title}</h2>
      <p className="mt-1 text-sm text-slate-700">{message}</p>
      <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
        {apiError ? (
          <div className="flex gap-1">
            <dt>Correlation ID:</dt>
            <dd className="font-mono">{apiError.correlationId}</dd>
          </div>
        ) : null}
        {apiError && apiError.status > 0 ? (
          <div className="flex gap-1">
            <dt>Status:</dt>
            <dd className="font-mono">{apiError.status}</dd>
          </div>
        ) : null}
      </dl>
      {onRetry ? (
        <button type="button" className="btn-secondary mt-3" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
