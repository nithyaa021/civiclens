import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams, Link } from "react-router-dom";
import { ArrowDownRight, ArrowUpRight, MapPin, Minus, RefreshCw, Repeat2 } from "lucide-react";
import { api } from "../lib/api";
import { usePageTitle } from "../lib/usePageTitle";
import { categories, categoryMeta } from "../lib/meta";
import { formatDate, formatNumber, relativeTime, shortId } from "../lib/format";
import { CategoryLabel } from "../components/Badges";
import { Sparkline } from "../components/Sparkline";
import { EmptyState, ErrorState, PageHeader } from "../components/States";
import { Skeleton } from "../components/Skeleton";
import type { Cluster, ComplaintCategory } from "../lib/types";

function trendSummary(trend: number[]): { delta: number; direction: "up" | "down" | "flat" } {
  if (trend.length < 4) return { delta: 0, direction: "flat" };
  const half = Math.floor(trend.length / 2);
  const previous = trend.slice(0, half).reduce((sum, value) => sum + value, 0);
  const recent = trend.slice(half).reduce((sum, value) => sum + value, 0);
  if (recent === previous) return { delta: 0, direction: "flat" };
  return { delta: previous === 0 ? 100 : Math.round(((recent - previous) / previous) * 100), direction: recent > previous ? "up" : "down" };
}

function ClusterCard({ cluster }: { cluster: Cluster }) {
  const meta = categoryMeta[cluster.category];
  const Icon = meta.icon;
  const trend = trendSummary(cluster.trend);

  return (
    <article className="card flex flex-col p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-line bg-raised">
            <Icon className={`h-4 w-4 ${meta.className}`} aria-hidden />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-[13px] font-semibold text-ink">
              {meta.label} · Ward {cluster.dominant_ward ?? "—"}
            </h2>
            <p className="mt-0.5 text-[11px] text-muted">
              {formatNumber(cluster.count)} reports · {formatNumber(cluster.open_count)} open
            </p>
          </div>
        </div>
        <span className="inline-flex h-6 shrink-0 items-center gap-1 rounded border border-line bg-raised px-1.5 text-[10px] font-medium text-muted">
          <Repeat2 className="h-3 w-3" aria-hidden />
          Recurring
        </span>
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-faint">
            Report volume
          </p>
          <p className="mt-0.5 flex items-baseline gap-2">
            <span className="tabular text-[20px] font-semibold leading-none text-ink">
              {formatNumber(cluster.count)}
            </span>
            <span
              className="inline-flex items-center gap-0.5 text-[11px] font-medium"
              style={{
                color:
                  trend.direction === "up"
                    ? "var(--critical)"
                    : trend.direction === "down"
                      ? "var(--positive)"
                      : "var(--muted)",
              }}
            >
              {trend.direction === "up" ? (
                <ArrowUpRight className="h-3 w-3" aria-hidden />
              ) : trend.direction === "down" ? (
                <ArrowDownRight className="h-3 w-3" aria-hidden />
              ) : (
                <Minus className="h-3 w-3" aria-hidden />
              )}
              {Math.abs(trend.delta)}%
            </span>
          </p>
        </div>
        <Sparkline values={cluster.trend} width={104} height={30} />
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-line pt-2.5 text-[11px]">
        <div>
          <dt className="text-faint">First reported</dt>
          <dd className="mt-0.5 text-ink">{formatDate(cluster.first_reported)}</dd>
        </div>
        <div>
          <dt className="text-faint">Last reported</dt>
          <dd className="mt-0.5 text-ink">{relativeTime(cluster.last_reported)}</dd>
        </div>
        <div>
          <dt className="text-faint">Affected radius</dt>
          <dd className="tabular mt-0.5 text-ink">{cluster.affected_area.radius_km.toFixed(1)} km</dd>
        </div>
        <div>
          <dt className="text-faint">Category</dt>
          <dd className="mt-0.5">
            <CategoryLabel category={cluster.category} showIcon={false} className="text-[11px]" />
          </dd>
        </div>
      </dl>

      <div className="mt-3 flex items-center gap-2 border-t border-line pt-2.5">
        <MapPin className="h-3 w-3 shrink-0 text-faint" aria-hidden />
        <div className="flex min-w-0 flex-1 flex-wrap gap-1">
          {cluster.complaint_ids.slice(0, 3).map((id) => (
            <Link
              key={id}
              to={`/queue/${id}`}
              className="tabular inline-flex h-5 items-center rounded border border-line bg-raised px-1.5 text-[10px] text-muted hover:text-primary"
              title="Open complaint"
            >
              {shortId(id)}
            </Link>
          ))}
          {cluster.complaint_ids.length > 3 ? (
            <span className="inline-flex h-5 items-center px-1 text-[10px] text-faint">
              +{cluster.complaint_ids.length - 3}
            </span>
          ) : null}
        </div>
        <Link
          to={`/queue?category=${cluster.category}&ward=${cluster.dominant_ward ?? ""}`}
          className="shrink-0 text-[11px] font-medium text-primary hover:underline"
        >
          View reports
        </Link>
      </div>
    </article>
  );
}

export function RecurringPage() {
  usePageTitle("Recurring issues");
  const [searchParams, setSearchParams] = useSearchParams();
  const category = (searchParams.get("category") || null) as ComplaintCategory | null;
  const wardParam = Number(searchParams.get("ward"));
  const ward = Number.isFinite(wardParam) && wardParam > 0 ? wardParam : null;
  const minParam = Number(searchParams.get("min_count"));
  const minCount = Number.isFinite(minParam) && minParam >= 2 ? minParam : 2;
  const queryClient = useQueryClient();

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next, { replace: true });
  };

  const clusters = useQuery({
    queryKey: ["clusters", category, ward, minCount],
    queryFn: () => api.clusters({ category, ward, min_count: minCount, limit: 60 }),
  });

  const wards = useQuery({ queryKey: ["wards"], queryFn: api.wards, staleTime: 120_000 });

  const recompute = useMutation({
    mutationFn: () => api.recomputeClusters(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["clusters"] });
    },
  });

  return (
    <div className="mx-auto max-w-[1440px] space-y-4">
      <PageHeader
        eyebrow="Pattern detection"
        title="Recurring issues"
        description={
          clusters.data
            ? `${formatNumber(clusters.data.items.length)} clusters from a ${clusters.data.lookback_days}-day lookback · grouped by category, location and text similarity.`
            : "Geospatial and semantic clusters of repeated reports."
        }
        actions={
          <>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => recompute.mutate()}
              disabled={recompute.isPending}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${recompute.isPending ? "animate-spin" : ""}`} aria-hidden />
              {recompute.isPending ? "Recomputing…" : "Recompute"}
            </button>
          </>
        }
      />

      <div className="card p-3">
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
          <div>
            <label htmlFor="cluster-category" className="label">
              Category
            </label>
            <select
              id="cluster-category"
              className="field"
              value={category ?? ""}
              onChange={(event) => update({ category: event.target.value || null })}
            >
              <option value="">All categories</option>
              {categories.map((item) => (
                <option key={item} value={item}>
                  {categoryMeta[item].label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cluster-ward" className="label">
              Ward
            </label>
            <select
              id="cluster-ward"
              className="field"
              value={ward ?? ""}
              onChange={(event) => update({ ward: event.target.value || null })}
            >
              <option value="">All wards</option>
              {(wards.data ?? []).map((item) => (
                <option key={item.ward_no} value={item.ward_no}>
                  {item.ward_no} · {item.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cluster-min" className="label">
              Minimum reports
            </label>
            <select
              id="cluster-min"
              className="field"
              value={minCount}
              onChange={(event) => update({ min_count: event.target.value === "2" ? null : event.target.value })}
            >
              {[2, 3, 5, 10].map((count) => (
                <option key={count} value={count}>
                  {count} or more
                </option>
              ))}
            </select>
          </div>
        </div>
        {recompute.isError ? (
          <p className="mt-2 text-[11px] text-[color:var(--critical)]" role="alert">
            {recompute.error instanceof Error ? recompute.error.message : "Recompute failed."}
          </p>
        ) : null}
        {recompute.data ? (
          <p className="mt-2 text-[11px] text-muted" role="status">
            Rebuilt {formatNumber(recompute.data.clusters)} clusters from current records.
          </p>
        ) : null}
      </div>

      {clusters.isPending ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="card space-y-3 p-4">
              <div className="flex gap-2.5">
                <Skeleton className="h-8 w-8" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3 w-2/3" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              </div>
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          ))}
        </div>
      ) : clusters.isError ? (
        <ErrorState error={clusters.error} onRetry={() => void clusters.refetch()} title="Recurring clusters unavailable" />
      ) : clusters.data.items.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No recurring clusters in this view"
            description="Lower the minimum report count or clear the category and ward filters. Clusters are recomputed from recent records every 30 minutes."
          />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {clusters.data.items.map((cluster) => (
              <ClusterCard key={cluster.id} cluster={cluster} />
            ))}
          </div>
          <p className="text-[11px] text-muted">
            Clusters are computed over the last {clusters.data.lookback_days} days. Snapshot generated{" "}
            {relativeTime(clusters.data.computed_at)}. Sparklines show daily reports across the past 14 days.
          </p>
        </>
      )}
    </div>
  );
}
