import {
  AlertOctagon,
  CheckCircle2,
  CircleDot,
  Gauge,
  Timer,
  type LucideIcon,
} from "lucide-react";
import { formatDays, formatNumber, formatPercent } from "../lib/format";
import type { KpiSummary } from "../lib/types";

interface KpiSpec {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  /** Accent ramp position; each card owns one colour for quick recognition. */
  accent: string;
  tint: string;
}

export function KpiCards({ kpis, periodDays }: { kpis: KpiSummary; periodDays: number }) {
  const cards: KpiSpec[] = [
    {
      label: "Open complaints",
      value: formatNumber(kpis.open),
      detail: kpis.open > 0 ? "Awaiting closure" : "No open items",
      icon: CircleDot,
      accent: "var(--aurora-2)",
      tint: "var(--warning-soft)",
    },
    {
      label: "Resolved",
      value: formatNumber(kpis.resolved_this_week),
      detail: `Last 7 days · ${periodDays}-day view`,
      icon: CheckCircle2,
      accent: "var(--positive)",
      tint: "var(--positive-soft)",
    },
    {
      label: "Avg. resolution",
      value: formatDays(kpis.avg_resolution_days),
      detail: "From report to resolution",
      icon: Timer,
      accent: "var(--aurora-3)",
      tint: "var(--info-soft)",
    },
    {
      label: "SLA breaches",
      value: formatNumber(kpis.sla_breaches),
      detail: kpis.sla_breaches === 0 ? "All clocks within target" : "Open past due time",
      icon: AlertOctagon,
      accent: "var(--critical)",
      tint: "var(--critical-soft)",
    },
    {
      label: "Resolved rate",
      value: formatPercent(kpis.resolved_rate, 1),
      detail: `${formatNumber(kpis.total)} recorded reports`,
      icon: Gauge,
      accent: "var(--aurora-4)",
      tint: "var(--primary-soft)",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div
            key={card.label}
            className="card panel-glow relative overflow-hidden p-4 transition-shadow hover:shadow-pop"
          >
            <span
              className="absolute inset-x-0 top-0 h-[3px]"
              style={{ background: card.accent }}
              aria-hidden
            />
            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint">
                {card.label}
              </p>
              <span
                className="flex h-7 w-7 items-center justify-center rounded-lg"
                style={{ background: card.tint, color: card.accent }}
                aria-hidden
              >
                <Icon className="h-4 w-4" />
              </span>
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
