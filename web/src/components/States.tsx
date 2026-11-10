import type { ReactNode } from "react";
import { AlertTriangle, Inbox, Loader2, RefreshCw } from "lucide-react";
import { ApiError } from "../lib/api";

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg border border-line bg-raised text-faint">
        {icon ?? <Inbox className="h-5 w-5" aria-hidden />}
      </div>
      <p className="text-[14px] font-semibold text-ink">{title}</p>
      <p className="mt-1 max-w-sm text-[13px] leading-5 text-muted">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  title = "Could not load this view",
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "The request failed. Check the API connection and try again.";
  return (
    <div
      className="flex flex-col items-start gap-3 border border-[color:var(--critical-border)] bg-[color:var(--critical-soft)] p-4 sm:flex-row sm:items-center"
      role="alert"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface text-[color:var(--critical)]">
        <AlertTriangle className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold text-ink">{title}</p>
        <p className="mt-0.5 text-[12px] leading-5 text-muted">{message}</p>
      </div>
      {onRetry ? (
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={`animate-spin ${className ?? "h-4 w-4"}`} aria-hidden />;
}

export function LoadingBlock({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-1 py-8 text-[13px] text-muted" role="status">
      <Spinner />
      {label}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-line pb-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow ? <p className="eyebrow mb-1">{eyebrow}</p> : null}
        <h1 className="text-[21px] font-semibold tracking-[-0.015em] text-ink">{title}</h1>
        {description ? (
          <p className="mt-1 max-w-2xl text-[13px] leading-5 text-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
