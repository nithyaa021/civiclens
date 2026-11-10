import { Info } from "lucide-react";
import { formatNumber } from "../lib/format";
import type { PriorityScore } from "../lib/types";

const LABELS: Record<string, string> = {
  severity: "Severity",
  frequency: "Citizen support",
  cluster_density: "Recurring cluster",
  age_unresolved: "Age unresolved",
  sensitive_proximity: "Near school / hospital",
};

export function PriorityBreakdown({ priority }: { priority: PriorityScore | null }) {
  if (!priority) {
    return (
      <p className="text-[12px] text-muted">
        The priority score has not been computed for this report yet.
      </p>
    );
  }

  const entries = Object.entries(priority.components).sort(
    (a, b) => b[1].contribution - a[1].contribution,
  );

  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-faint">
            Priority score
          </p>
          <p className="tabular mt-1 text-[26px] font-semibold leading-none text-ink">
            {Math.round(priority.score)}
            <span className="ml-1 text-[12px] font-normal text-faint">/ 100</span>
          </p>
        </div>
        <span
          className="inline-flex h-6 items-center rounded border px-2 text-[10px] font-medium"
          style={{
            borderColor:
              priority.score >= 70
                ? "var(--critical-border)"
                : priority.score >= 45
                  ? "var(--warning-border)"
                  : "var(--positive-border)",
            background:
              priority.score >= 70
                ? "var(--critical-soft)"
                : priority.score >= 45
                  ? "var(--warning-soft)"
                  : "var(--positive-soft)",
            color:
              priority.score >= 70
                ? "var(--critical)"
                : priority.score >= 45
                  ? "var(--warning)"
                  : "var(--positive)",
          }}
        >
          {priority.score >= 70 ? "High" : priority.score >= 45 ? "Elevated" : "Routine"}
        </span>
      </div>

      <dl className="mt-3 space-y-2">
        {entries.map(([key, component]) => (
          <div key={key}>
            <div className="flex items-baseline justify-between gap-2">
              <dt className="truncate text-[11px] text-muted">{LABELS[key] ?? key}</dt>
              <dd className="tabular shrink-0 text-[11px] font-medium text-ink">
                {formatNumber(component.contribution)}
                <span className="ml-1 font-normal text-faint">pts</span>
              </dd>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised" aria-hidden>
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min(100, component.normalized * 100)}%`,
                    background: "var(--primary)",
                    opacity: 0.8,
                  }}
                />
              </div>
              <span className="tabular w-9 shrink-0 text-right text-[10px] text-faint">
                ×{component.weight}
              </span>
            </div>
          </div>
        ))}
      </dl>

      <p className="mt-3 flex items-start gap-1.5 border-t border-line pt-2 text-[10px] leading-4 text-faint">
        <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
        {priority.formula}
      </p>
    </div>
  );
}
