import {
  AlertOctagon,
  CheckCircle2,
  CircleDot,
  Gauge,
  Timer,
  type LucideIcon,
} from "lucide-react";
import { clsx } from "clsx";
import { formatDays, formatNumber, formatPercent } from "../lib/format";
import type { KpiSummary } from "../lib/types";

interface KpiSpec {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  tone?: "default" | "positive" | "warning" | "critical";
}

export function KpiCards({ kpis, periodDays }: { kpis: KpiSummary; periodDays: number }) {
  const cards: KpiSpec[] = [
    {
      label: "Open complaints",
      value: formatNumber(kpis.open),
      detail: kpis.open > 0 ? "Awaiting closure" : "No open items",
      icon: CircleDot,
      tone: kpis.open > 0 ? "warning" : "positive",
    },
    {
      label: "Resolved",
      value: formatNumber(kpis.resolved_this_week),
      detail: `Last 7 days · ${periodDays}-day view`,
      icon: CheckCircle2,
      tone: "positive",
    },
    {
      label: "Avg. resolution",
      value: formatDays(kpis.avg_resolution_days),
      detail: "From report to resolution",
      icon: Timer,
    },
    {
      label: "SLA breaches",
      value: formatNumber(kpis.sla_breaches),
      detail: kpis.sla_breaches === 0 ? "All clocks within target" : "Open past due time",
      icon: AlertOctagon,
      tone: kpis.sla_breaches > 0 ? "critical" : "positive",
    },
    {
      label: "Resolved rate",
      value: formatPercent(kpis.resolved_rate, 1),
      detail: `${formatNumber(kpis.total)} recorded reports`,
      icon: Gauge,
      tone: "default",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2 xl:grid-cols-5">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div key={card.label} className="bg-surface p-4">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint">
                {card.label}
              </p>
              <Icon
                className={clsx(
                  "h-3.5 w-3.5",
                  card.tone === "critical"
                    ? "text-[color:var(--critical)]"
                    : card.tone === "warning"
                      ? "text-[color:var(--warning)]"
                      : card.tone === "positive"
                        ? "text-[color:var(--positive)]"
                        : "text-faint",
                )}
                aria-hidden
              />
            </div>
            <p className="stat-value mt-2.5">{card.value}</p>
            <p className="mt-1.5 truncate text-[11px] text-muted" title={card.detail}>
              {card.detail}
            </p>
          </div>
        );
      })}
    </div>
  );
}
