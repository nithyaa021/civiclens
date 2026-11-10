import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { categoryMeta } from "../lib/meta";
import { formatNumber, formatPercent } from "../lib/format";
import type { CategoryStat } from "../lib/types";

export function CategoryBreakdown({ items }: { items: CategoryStat[] }) {
  const sorted = [...items].sort((a, b) => b.count - a.count);
  const max = Math.max(1, ...sorted.map((item) => item.count));

  return (
    <div className="card flex h-full flex-col p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <h2 className="section-title">Category mix</h2>
          <p className="mt-0.5 text-[11px] text-muted">Volume and open share by category</p>
        </div>
        <Link to="/queue" className="btn btn-ghost btn-sm">
          View queue
          <ArrowRight className="h-3 w-3" aria-hidden />
        </Link>
      </div>

      <ul className="space-y-2.5">
        {sorted.map((item) => {
          const meta = categoryMeta[item.category];
          const Icon = meta.icon;
          return (
            <li key={item.category}>
              <Link
                to={`/queue?category=${item.category}`}
                className="group block rounded px-1 py-0.5"
                title={`Open ${meta.label} complaints`}
              >
                <div className="flex items-center gap-2">
                  <Icon className={`h-3.5 w-3.5 shrink-0 ${meta.className}`} aria-hidden />
                  <span className="truncate text-[12px] text-ink group-hover:underline">
                    {meta.label}
                  </span>
                  <span className="tabular ml-auto shrink-0 text-[12px] font-medium text-ink">
                    {formatNumber(item.count)}
                  </span>
                  <span className="tabular w-9 shrink-0 text-right text-[11px] text-faint">
                    {formatPercent(item.share, 0)}
                  </span>
                </div>
                <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-raised" aria-hidden>
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${(item.count / max) * 100}%`,
                      background: "var(--primary)",
                      opacity: 0.68,
                    }}
                  />
                  <div
                    className="h-full"
                    style={{
                      width: `${(item.open / max) * 100}%`,
                      background: "var(--warning)",
                      opacity: 0.68,
                    }}
                  />
                </div>
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="mt-auto flex items-center gap-3 border-t border-line pt-2.5 text-[10px] text-faint">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-1.5 w-3 rounded-full" style={{ background: "var(--primary)" }} aria-hidden />
          Total
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="h-1.5 w-3 rounded-full"
            style={{ background: "var(--warning)" }}
            aria-hidden
          />
          Still open
        </span>
      </div>
    </div>
  );
}
