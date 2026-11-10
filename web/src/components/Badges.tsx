import { clsx } from "clsx";
import type { ReactNode } from "react";
import { CheckCircle2, ShieldAlert, Timer } from "lucide-react";
import { categoryMeta, severityLabel, statusMeta } from "../lib/meta";
import { slaDeadline } from "../lib/format";
import type { ComplaintCategory, ComplaintStatus, SlaState } from "../lib/types";

export function StatusBadge({
  status,
  className,
}: {
  status: ComplaintStatus;
  className?: string;
}) {
  const meta = statusMeta[status];
  return (
    <span
      className={clsx(
        "inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full border px-2 text-[11px] font-medium",
        meta.className,
        className,
      )}
    >
      <span className={clsx("h-1.5 w-1.5 rounded-full", meta.dot)} aria-hidden />
      {meta.label}
    </span>
  );
}

export function CategoryLabel({
  category,
  showIcon = true,
  className,
}: {
  category: ComplaintCategory;
  showIcon?: boolean;
  className?: string;
}) {
  const meta = categoryMeta[category];
  const Icon = meta.icon;
  return (
    <span className={clsx("inline-flex min-w-0 items-center gap-1.5 text-[13px]", className)}>
      {showIcon ? (
        <Icon className={clsx("h-3.5 w-3.5 shrink-0", meta.className)} aria-hidden />
      ) : null}
      <span className="truncate">{meta.label}</span>
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: number }) {
  const tone =
    severity >= 5
      ? "border-[color:var(--critical-border)] bg-[color:var(--critical-soft)] text-[color:var(--critical)]"
      : severity === 4
        ? "border-[color:var(--warning-border)] bg-[color:var(--warning-soft)] text-[color:var(--warning)]"
        : "border-line bg-raised text-muted";
  return (
    <span
      className={clsx(
        "inline-flex h-5 items-center rounded border px-1.5 text-[10px] font-semibold uppercase tracking-[0.04em]",
        tone,
      )}
      title={`Severity ${severity} of 5`}
    >
      {severityLabel[severity] ?? severity}
    </span>
  );
}

export function SlaChip({ sla, status }: { sla: SlaState | null; status: ComplaintStatus }) {
  const deadline = slaDeadline(sla?.due_at ?? null, status);
  const tone =
    deadline.tone === "critical"
      ? "border-[color:var(--critical-border)] bg-[color:var(--critical-soft)] text-[color:var(--critical)]"
      : deadline.tone === "warning"
        ? "border-[color:var(--warning-border)] bg-[color:var(--warning-soft)] text-[color:var(--warning)]"
        : deadline.tone === "done"
          ? "border-[color:var(--positive-border)] bg-[color:var(--positive-soft)] text-[color:var(--positive)]"
          : "border-line bg-raised text-muted";
  return (
    <span
      className={clsx(
        "tabular inline-flex h-5 items-center gap-1 rounded border px-1.5 text-[10px] font-medium",
        tone,
      )}
    >
      {deadline.tone === "critical" ? (
        <ShieldAlert className="h-3 w-3" aria-hidden />
      ) : deadline.tone === "done" ? (
        <CheckCircle2 className="h-3 w-3" aria-hidden />
      ) : (
        <Timer className="h-3 w-3" aria-hidden />
      )}
      {deadline.label}
    </span>
  );
}

export function Tag({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "info" | "positive" }) {
  const tones = {
    neutral: "border-line bg-raised text-muted",
    info: "border-[color:var(--info-border)] bg-[color:var(--info-soft)] text-[color:var(--info)]",
    positive:
      "border-[color:var(--positive-border)] bg-[color:var(--positive-soft)] text-[color:var(--positive)]",
  };
  return (
    <span
      className={clsx(
        "inline-flex h-5 items-center rounded border px-1.5 text-[10px] font-medium",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}
