import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpDown,
  BadgeCheck,
  Building2,
  Moon,
  ShieldCheck,
  Sun,
} from "lucide-react";
import { api } from "../lib/api";
import { useTheme } from "../lib/themeContext";
import { usePageTitle } from "../lib/usePageTitle";
import { formatDate, formatDateTime, formatDays, formatNumber, formatPercent } from "../lib/format";
import { CategoryLabel } from "../components/Badges";
import { KpiCards } from "../components/KpiCards";
import { KpiSkeleton, TableSkeleton } from "../components/Skeleton";
import { EmptyState, ErrorState } from "../components/States";
import { Wordmark } from "../components/Wordmark";
import type { PublicWardStat } from "../lib/types";

type SortKey = keyof Pick<
  PublicWardStat,
  "ward" | "total" | "open" | "resolved" | "avg_resolution_days" | "sla_compliance" | "resolved_rate"
>;

const SORTABLE: { key: SortKey; label: string; align?: "right" }[] = [
  { key: "total", label: "Reports", align: "right" },
  { key: "open", label: "Open", align: "right" },
  { key: "resolved", label: "Resolved", align: "right" },
  { key: "avg_resolution_days", label: "Avg. days", align: "right" },
  { key: "sla_compliance", label: "SLA", align: "right" },
  { key: "resolved_rate", label: "Resolved", align: "right" },
];

export function PublicPage() {
  usePageTitle("Public transparency");
  const { theme, toggle } = useTheme();
  const [sort, setSort] = useState<{ key: SortKey; direction: "asc" | "desc" }>({
    key: "ward",
    direction: "asc",
  });

  const stats = useQuery({ queryKey: ["public-stats"], queryFn: api.publicStats, staleTime: 60_000 });

  const wards = useMemo(() => {
    const items = [...(stats.data?.wards ?? [])];
    items.sort((a, b) => {
      const left = a[sort.key] ?? Number.POSITIVE_INFINITY;
      const right = b[sort.key] ?? Number.POSITIVE_INFINITY;
      return sort.direction === "asc" ? Number(left) - Number(right) : Number(right) - Number(left);
    });
    return items;
  }, [stats.data, sort]);

  const maxCategory = Math.max(1, ...(stats.data?.categories ?? []).map((item) => item.total));

  return (
    <div className="min-h-screen bg-canvas">
      <a
        href="#public-main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:text-[13px] focus:shadow-pop"
      >
        Skip to content
      </a>

      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <Wordmark />
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-ghost h-8 w-8 px-0"
              onClick={toggle}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            >
              {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
            </button>
            <Link to="/login" className="btn btn-secondary btn-sm">
              Staff sign in
            </Link>
          </div>
        </div>
      </header>

      <main id="public-main" className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
        <div className="flex flex-col gap-3 border-b border-line pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="eyebrow mb-1.5">Public transparency portal</p>
            <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.025em] text-ink">
              Municipal complaint performance
            </h1>
            <p className="mt-2 max-w-2xl text-[13px] leading-6 text-muted">
              Aggregate resolution performance for Bengaluru wards. Figures are derived from live
              municipal records and refreshed at least once per minute.
            </p>
          </div>
          <dl className="shrink-0 text-[11px] text-muted">
            <div className="flex gap-2">
              <dt>Reporting window</dt>
              <dd className="font-medium text-ink">
                {stats.data ? `${stats.data.period_days} days` : "—"}
              </dd>
            </div>
            <div className="mt-1 flex gap-2">
              <dt>Generated</dt>
              <dd className="tabular font-medium text-ink">
                {stats.data ? formatDateTime(stats.data.generated_at) : "—"}
              </dd>
            </div>
          </dl>
        </div>

        {stats.isPending ? (
          <div className="mt-6 space-y-4">
            <KpiSkeleton />
            <TableSkeleton rows={8} columns={7} />
          </div>
        ) : stats.isError ? (
          <div className="mt-6">
            <ErrorState
              error={stats.error}
              onRetry={() => void stats.refetch()}
              title="Transparency statistics are temporarily unavailable"
            />
          </div>
        ) : (
          <>
            <section className="mt-6" aria-label="City-wide totals">
              <KpiCards kpis={stats.data.totals} periodDays={stats.data.period_days} />
              <p className="mt-2 text-[11px] text-muted">
                {formatNumber(stats.data.resolved_in_period)} complaints were completed within the
                reporting window across {stats.data.wards.length} wards.
              </p>
            </section>

            <section className="mt-8" aria-labelledby="ward-table-heading">
              <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
                <div>
                  <h2 id="ward-table-heading" className="text-[15px] font-semibold text-ink">
                    Ward performance
                  </h2>
                  <p className="mt-0.5 text-[11px] text-muted">
                    Sort by any measure. SLA compliance is the share of completed cases resolved
                    before their target time.
                  </p>
                </div>
              </div>

              <div className="overflow-x-auto rounded-lg border border-line bg-surface">
                <table className="data-table min-w-[820px]">
                  <caption className="sr-only">
                    Aggregate complaint performance for each municipal ward.
                  </caption>
                  <thead>
                    <tr>
                      <th className="w-[190px]">
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 uppercase tracking-[0.06em] hover:text-ink"
                          onClick={() =>
                            setSort({
                              key: "ward",
                              direction: sort.key === "ward" && sort.direction === "asc" ? "desc" : "asc",
                            })
                          }
                        >
                          Ward
                          <ArrowUpDown className="h-3 w-3" aria-hidden />
                        </button>
                      </th>
                      <th>Zone</th>
                      {SORTABLE.map((column) => (
                        <th key={column.key} className="text-right">
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 uppercase tracking-[0.06em] hover:text-ink"
                            onClick={() =>
                              setSort({
                                key: column.key,
                                direction:
                                  sort.key === column.key && sort.direction === "desc" ? "asc" : "desc",
                              })
                            }
                          >
                            {column.label}
                            <ArrowUpDown className="h-3 w-3" aria-hidden />
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {wards.map((ward) => (
                      <tr key={ward.ward}>
                        <td>
                          <span className="flex items-center gap-2">
                            <span className="tabular flex h-5 w-5 items-center justify-center rounded border border-line bg-raised text-[10px] font-medium text-muted">
                              {ward.ward}
                            </span>
                            <span className="truncate font-medium text-ink">{ward.name}</span>
                          </span>
                        </td>
                        <td className="text-[12px] text-muted">{ward.zone}</td>
                        <td className="tabular text-right text-[12px] text-ink">{formatNumber(ward.total)}</td>
                        <td className="tabular text-right text-[12px] text-ink">{formatNumber(ward.open)}</td>
                        <td className="tabular text-right text-[12px] text-ink">{formatNumber(ward.resolved)}</td>
                        <td className="tabular text-right text-[12px] text-ink">{formatDays(ward.avg_resolution_days)}</td>
                        <td className="tabular text-right text-[12px] text-ink">{formatPercent(ward.sla_compliance, 0)}</td>
                        <td className="text-right">
                          <span className="inline-flex items-center justify-end gap-1.5">
                            <span className="tabular text-[12px] font-medium text-ink">
                              {formatPercent(ward.resolved_rate, 0)}
                            </span>
                            <span className="h-1 w-10 overflow-hidden rounded-full bg-raised" aria-hidden>
                              <span
                                className="block h-full rounded-full"
                                style={{
                                  width: `${Math.round(ward.resolved_rate * 100)}%`,
                                  background: "var(--positive)",
                                  opacity: 0.75,
                                }}
                              />
                            </span>
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2">
              <section aria-labelledby="public-categories">
                <h2 id="public-categories" className="text-[15px] font-semibold text-ink">
                  Complaint categories
                </h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  Share of reports received in the last {stats.data.period_days} days.
                </p>
                <ul className="mt-3 space-y-2.5 rounded-lg border border-line bg-surface p-4">
                  {stats.data.categories.length === 0 ? (
                    <li className="py-4 text-center text-[12px] text-muted">No category data.</li>
                  ) : (
                    stats.data.categories.map((item) => {
                      const resolvedShare = item.total > 0 ? item.resolved / item.total : 0;
                      return (
                        <li key={item.category}>
                          <div className="flex items-center gap-2">
                            <CategoryLabel category={item.category} className="text-[12px]" />
                            <span className="tabular ml-auto text-[12px] font-medium text-ink">
                              {formatNumber(item.total)}
                            </span>
                            <span className="tabular w-10 text-right text-[11px] text-faint">
                              {formatPercent(item.share, 0)}
                            </span>
                          </div>
                          <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-raised" aria-hidden>
                            <span
                              className="h-full rounded-full"
                              style={{
                                width: `${(item.total / maxCategory) * 100}%`,
                                background: "var(--primary)",
                                opacity: 0.7,
                              }}
                            />
                            <span
                              className="h-full bg-[color:var(--positive)]"
                              style={{
                                width: `${(item.total / maxCategory) * resolvedShare * 100}%`,
                                opacity: 0.55,
                              }}
                            />
                          </div>
                        </li>
                      );
                    })
                  )}
                </ul>
              </section>

              <section aria-labelledby="recent-resolutions">
                <h2 id="recent-resolutions" className="text-[15px] font-semibold text-ink">
                  Recently completed work
                </h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  Titles are shown as reported. Reporter, officer and exact location are omitted.
                </p>
                <div className="mt-3 overflow-hidden rounded-lg border border-line bg-surface">
                  {stats.data.recent_resolutions.length === 0 ? (
                    <EmptyState
                      title="No recent resolutions"
                      description="Completed work will be listed here once cases are verified and closed."
                    />
                  ) : (
                    <ul className="divide-y divide-line">
                      {stats.data.recent_resolutions.slice(0, 8).map((item, index) => (
                        <li key={`${item.title}-${index}`} className="flex items-start gap-2.5 px-4 py-2.5">
                          <span
                            className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border"
                            style={{
                              borderColor: item.verified
                                ? "var(--positive-border)"
                                : "var(--line)",
                              background: item.verified ? "var(--positive-soft)" : "var(--raised)",
                              color: item.verified ? "var(--positive)" : "var(--faint)",
                            }}
                          >
                            {item.verified ? (
                              <BadgeCheck className="h-3.5 w-3.5" aria-hidden />
                            ) : (
                              <Building2 className="h-3.5 w-3.5" aria-hidden />
                            )}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-[12px] font-medium text-ink">{item.title}</p>
                            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px] text-muted">
                              <CategoryLabel category={item.category} showIcon={false} className="text-[10px]" />
                              <span>{item.ward_name ? `${item.ward_name} · Ward ${item.ward}` : "City-wide"}</span>
                              <span>{formatDate(item.resolved_at)}</span>
                              {item.resolution_days !== null ? (
                                <span>{formatDays(item.resolution_days)} to resolve</span>
                              ) : null}
                            </p>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </section>
            </div>

            <section className="mt-8 rounded-lg border border-line bg-surface p-4" aria-labelledby="methodology">
              <h2 id="methodology" className="flex items-center gap-2 text-[13px] font-semibold text-ink">
                <ShieldCheck className="h-4 w-4 text-[color:var(--positive)]" aria-hidden />
                Methodology and privacy
              </h2>
              <div className="mt-2 grid grid-cols-1 gap-3 text-[11px] leading-5 text-muted sm:grid-cols-3">
                <p>
                  Figures aggregate municipal complaint records over the reporting window. A case
                  counts as resolved when field evidence passes image verification.
                </p>
                <p>
                  Reporter identity, officer identity, contact details and precise coordinates are
                  excluded from this portal. Ward-level totals are the finest geography published.
                </p>
                <p>
                  Response times are measured from report creation to resolution submission. SLA
                  compliance uses each category&apos;s configured target.
                </p>
              </div>
            </section>
          </>
        )}

        <footer className="mt-10 flex flex-col gap-2 border-t border-line pt-4 text-[10px] text-faint sm:flex-row sm:items-center sm:justify-between">
          <span>CivicLens · {stats.data?.generated_for ?? "Municipal transparency portal"}</span>
          <span>
            Data refreshed {stats.data ? formatDateTime(stats.data.generated_at) : "periodically"} ·{" "}
            <Link to="/login" className="underline hover:text-ink">
              Staff access
            </Link>
          </span>
        </footer>
      </main>
    </div>
  );
}
