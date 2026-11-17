import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { usePageTitle } from "../lib/usePageTitle";
import { formatNumber, relativeTime } from "../lib/format";
import { CategoryBreakdown } from "../components/CategoryBreakdown";
import { KpiCards } from "../components/KpiCards";
import { KpiSkeleton, ChartSkeleton, Skeleton, TableSkeleton } from "../components/Skeleton";
import { EmptyState, ErrorState, PageHeader } from "../components/States";
import { TrendChart } from "../components/TrendChart";
import { CategoryLabel, SlaChip, StatusBadge } from "../components/Badges";

const PERIODS = [7, 30, 90, 180];

export function OverviewPage() {
  usePageTitle("Operations overview");
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = Number(searchParams.get("period"));
  const periodDays = PERIODS.includes(requested) ? requested : 30;
  const [isRefreshing, setRefreshing] = useState(false);

  const overview = useQuery({
    queryKey: ["overview", periodDays],
    queryFn: () => api.overview(periodDays),
  });

  const wards = useQuery({ queryKey: ["wards"], queryFn: api.wards, staleTime: 120_000 });

  const priority = useQuery({
    queryKey: ["priority-open", user?.id, user?.ward],
    queryFn: () =>
      api.complaints({
        page_size: 8,
        sort: "priority",
        ward: user?.role === "ward_officer" ? user.ward : null,
      }),
  });

  const openPriority = useMemo(
    () =>
      (priority.data?.items ?? [])
        .filter((item) => ["submitted", "assigned", "in_progress"].includes(item.status))
        .slice(0, 5),
    [priority.data],
  );

  const wardRows = useMemo(() => {
    const list = (wards.data ?? [])
      .filter((ward) => (user?.role === "ward_officer" ? ward.ward_no === user.ward : true))
      .sort((a, b) => b.complaint_count - a.complaint_count)
      .slice(0, 6);
    const max = Math.max(1, ...list.map((ward) => ward.complaint_count));
    return { list, max };
  }, [wards.data, user]);

  const refresh = async () => {
    setRefreshing(true);
    await Promise.all([overview.refetch(), wards.refetch(), priority.refetch()]);
    setRefreshing(false);
  };

  return (
    <div className="mx-auto max-w-[1440px] space-y-4">
      <PageHeader
        eyebrow="Authority dashboard"
        title="Operations overview"
        description={
          overview.data
            ? `${overview.data.scope === "ward" ? `Ward ${overview.data.ward} · ` : "City-wide · "}${formatNumber(overview.data.kpis.total)} reports in the last ${overview.data.period_days} days.`
            : "Live complaint performance across the municipal service area."
        }
        actions={
          <>
            <label htmlFor="overview-period" className="sr-only">
              Reporting period
            </label>
            <select
              id="overview-period"
              className="field h-8 w-[128px]"
              value={periodDays}
              onChange={(event) => {
                const next = new URLSearchParams(searchParams);
                next.set("period", event.target.value);
                setSearchParams(next, { replace: true });
              }}
            >
              {PERIODS.map((days) => (
                <option key={days} value={days}>
                  Last {days} days
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => void refresh()}
              disabled={isRefreshing}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`} aria-hidden />
              Refresh
            </button>
          </>
        }
      />

      {overview.isPending ? (
        <KpiSkeleton />
      ) : overview.isError ? (
        <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
      ) : (
        <KpiCards kpis={overview.data.kpis} periodDays={overview.data.period_days} />
      )}

      <div className="grid grid-cols-1 items-stretch gap-4 xl:grid-cols-3">
        {overview.isPending ? (
          <div className="xl:col-span-2">
            <ChartSkeleton height={220} />
          </div>
        ) : overview.isError ? null : (
          <div className="xl:col-span-2">
            <TrendChart points={overview.data.trend} />
          </div>
        )}
        {overview.isPending ? (
          <div className="card flex h-full flex-col p-4">
            <div className="mb-3 flex items-start justify-between gap-2">
              <div>
                <Skeleton className="h-[19px] w-24" />
                <Skeleton className="mt-0.5 h-4 w-40" />
              </div>
              <Skeleton className="h-7 w-20 rounded-md" />
            </div>
            <div className="space-y-2.5">
              {Array.from({ length: 10 }).map((_, index) => (
                <div key={index} className="px-1 py-0.5">
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-3.5 w-3.5 shrink-0" />
                    <Skeleton className="h-[17px] w-24" />
                    <Skeleton className="ml-auto h-[17px] w-8 shrink-0" />
                    <Skeleton className="h-[17px] w-9 shrink-0" />
                  </div>
                  <Skeleton className="mt-1 h-1.5 w-full rounded-full" />
                </div>
              ))}
            </div>
            <div className="mt-auto flex items-center gap-3 border-t border-line pt-2.5">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-4 w-16" />
            </div>
          </div>
        ) : overview.isError ? null : (
          <CategoryBreakdown items={overview.data.categories} />
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <section className="card overflow-hidden xl:col-span-2" aria-labelledby="priority-heading">
          <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
            <div>
              <h2 id="priority-heading" className="section-title">
                Highest priority open items
              </h2>
              <p className="mt-0.5 text-[11px] text-muted">
                Ranked by the live priority score · severity, age, support and location risk
              </p>
            </div>
            <Link to="/queue?sort=priority" className="btn btn-ghost btn-sm">
              Open queue
              <ArrowRight className="h-3 w-3" aria-hidden />
            </Link>
          </div>
          {priority.isPending ? (
            <div className="p-4">
              <TableSkeleton rows={5} columns={4} />
            </div>
          ) : priority.isError ? (
            <div className="p-4">
              <ErrorState
                error={priority.error}
                onRetry={() => void priority.refetch()}
                title="Priority queue unavailable"
              />
            </div>
          ) : openPriority.length === 0 ? (
            <EmptyState
              title="No open priority items"
              description="Every report currently in scope has been closed. New submissions will appear here."
            />
          ) : (
            <ul className="divide-y divide-line">
              {openPriority.map((item) => (
                <li key={item.id}>
                  <Link
                    to={`/queue/${item.id}`}
                    className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-raised"
                  >
                    <span
                      className="tabular flex h-7 w-9 shrink-0 items-center justify-center rounded border border-line bg-raised text-[12px] font-semibold text-ink"
                      title={`Priority ${item.priority?.score ?? 0}`}
                    >
                      {item.priority ? Math.round(item.priority.score) : "—"}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium text-ink">
                        {item.title}
                      </span>
                      <span className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
                        <CategoryLabel category={item.category} className="text-[11px]" />
                        <span aria-hidden>·</span>
                        <span className="tabular">Ward {item.ward ?? "—"}</span>
                        <span aria-hidden>·</span>
                        <span>{relativeTime(item.created_at)}</span>
                      </span>
                    </span>
                    <span className="hidden shrink-0 items-center gap-2 sm:flex">
                      <SlaChip sla={item.sla} status={item.status} />
                      <StatusBadge status={item.status} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card flex flex-col" aria-labelledby="wards-heading">
          <div className="border-b border-line px-4 py-3">
            <h2 id="wards-heading" className="section-title">
              Open load by ward
            </h2>
            <p className="mt-0.5 text-[11px] text-muted">
              Current open complaints · {user?.role === "ward_officer" ? "your ward" : "top six wards"}
            </p>
          </div>
          {wards.isPending ? (
            <div className="space-y-3 p-4">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-7" />
              ))}
            </div>
          ) : wards.isError ? (
            <div className="p-4">
              <ErrorState error={wards.error} onRetry={() => void wards.refetch()} title="Ward data unavailable" />
            </div>
          ) : wardRows.list.length === 0 ? (
            <EmptyState title="No wards in scope" description="Ward boundaries are not configured for this account." />
          ) : (
            <ul className="space-y-3 p-4">
              {wardRows.list.map((ward) => (
                <li key={ward.ward_no}>
                  <div className="mb-1 flex items-baseline justify-between gap-2">
                    <Link
                      to={`/map?ward=${ward.ward_no}`}
                      className="truncate text-[12px] text-ink hover:text-primary hover:underline"
                    >
                      {ward.ward_no} · {ward.name}
                    </Link>
                    <span className="tabular text-[12px] font-medium text-ink">
                      {formatNumber(ward.complaint_count)}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-raised" aria-hidden>
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${(ward.complaint_count / wardRows.max) * 100}%`,
                        background: "linear-gradient(90deg, var(--aurora-4), var(--aurora-3))",
                      }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-auto flex items-center justify-between border-t border-line px-4 py-2.5 text-[11px] text-muted">
            <span>{wards.data ? `${wards.data.length} wards configured` : "—"}</span>
            <Link to="/map" className="btn btn-ghost btn-sm">
              Map
              <ArrowRight className="h-3 w-3" aria-hidden />
            </Link>
          </div>
        </section>
      </div>
    </div>
  );
}
