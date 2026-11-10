import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Flame, Layers, RefreshCw, TriangleAlert } from "lucide-react";
import { api } from "../lib/api";
import { useTheme } from "../lib/themeContext";
import { usePageTitle } from "../lib/usePageTitle";
import { categories, categoryMeta, statusMeta, statusOptions } from "../lib/meta";
import { formatNumber } from "../lib/format";
import { CivicMap } from "../components/CivicMap";
import { ErrorState, PageHeader } from "../components/States";
import { Skeleton } from "../components/Skeleton";
import type { ComplaintCategory, ComplaintStatus } from "../lib/types";

export function MapPage() {
  usePageTitle("City map");
  const { theme } = useTheme();
  const [searchParams, setSearchParams] = useSearchParams();

  const category = (searchParams.get("category") || null) as ComplaintCategory | null;
  const status = (searchParams.get("status") || null) as ComplaintStatus | null;
  const wardParam = Number(searchParams.get("ward"));
  const ward = Number.isFinite(wardParam) && wardParam > 0 ? wardParam : null;
  const heat = searchParams.get("heat") === "1";
  const forecastCategory = (searchParams.get("forecast") || null) as ComplaintCategory | null;

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next, { replace: true });
  };

  const points = useQuery({
    queryKey: ["map", category, status, ward],
    queryFn: () => api.mapPoints({ category, status, ward, limit: 1500 }),
  });

  const wards = useQuery({ queryKey: ["wards"], queryFn: api.wards, staleTime: 120_000 });

  const forecast = useQuery({
    queryKey: ["forecast-map", forecastCategory],
    queryFn: () => api.forecastMap(forecastCategory as ComplaintCategory, 14),
    enabled: Boolean(forecastCategory),
    retry: false,
  });

  const maxForecast = useMemo(
    () => Math.max(1, ...(forecast.data?.items ?? []).map((item) => item.total_predicted)),
    [forecast.data],
  );

  return (
    <div className="mx-auto max-w-[1440px] space-y-4">
      <PageHeader
        eyebrow="Geospatial operations"
        title="City map"
        description="Clustered complaint points, ward boundaries, density heat and a 14-day forecast overlay."
        actions={
          <>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setSearchParams(new URLSearchParams(), { replace: true })}
            >
              Reset view
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                void points.refetch();
                void wards.refetch();
                if (forecastCategory) void forecast.refetch();
              }}
              disabled={points.isFetching}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${points.isFetching ? "animate-spin" : ""}`} aria-hidden />
              Refresh
            </button>
          </>
        }
      />

      <div className="card p-3">
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4 xl:grid-cols-[repeat(4,minmax(130px,1fr))_auto]">
          <div>
            <label htmlFor="map-category" className="label">
              Category
            </label>
            <select
              id="map-category"
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
            <label htmlFor="map-status" className="label">
              Status
            </label>
            <select
              id="map-status"
              className="field"
              value={status ?? ""}
              onChange={(event) => update({ status: event.target.value || null })}
            >
              <option value="">All statuses</option>
              {statusOptions.map((item) => (
                <option key={item} value={item}>
                  {statusMeta[item].label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="map-ward" className="label">
              Ward
            </label>
            <select
              id="map-ward"
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
            <label htmlFor="map-forecast" className="label">
              Forecast overlay
            </label>
            <select
              id="map-forecast"
              className="field"
              value={forecastCategory ?? ""}
              onChange={(event) => update({ forecast: event.target.value || null })}
            >
              <option value="">Off</option>
              {categories.map((item) => (
                <option key={item} value={item}>
                  {categoryMeta[item].label}
                </option>
              ))}
            </select>
          </div>
          <div className="col-span-2 flex items-end gap-2 md:col-span-1">
            <button
              type="button"
              className={`btn btn-sm w-full ${heat ? "btn-primary" : "btn-secondary"}`}
              aria-pressed={heat}
              onClick={() => update({ heat: heat ? null : "1" })}
            >
              <Flame className="h-3.5 w-3.5" aria-hidden />
              Heat
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm w-full"
              onClick={() => update({ category: null, status: null, ward: null })}
              title="Clear category, status and ward filters"
            >
              <Layers className="h-3.5 w-3.5" aria-hidden />
              Clear
            </button>
          </div>
        </div>
      </div>

      {points.isError ? (
        <ErrorState error={points.error} onRetry={() => void points.refetch()} title="Map points unavailable" />
      ) : null}
      {forecastCategory && forecast.isError ? (
        <ErrorState
          error={forecast.error}
          onRetry={() => void forecast.refetch()}
          title="Forecast overlay unavailable"
        />
      ) : null}

      <div className="relative overflow-hidden rounded-lg border border-line bg-surface shadow-panel">
        <div className="relative h-[calc(100vh-300px)] min-h-[520px] max-h-[860px]">
          {points.isPending ? (
            <div className="absolute inset-0 z-10 space-y-3 bg-surface p-5">
              <Skeleton className="h-8 w-60" />
              <Skeleton className="h-[80%] w-full" />
            </div>
          ) : null}

          <CivicMap
            complaints={points.data?.items ?? []}
            wards={wards.data ?? []}
            heat={heat}
            forecast={forecast.data ?? null}
            showForecast={Boolean(forecastCategory)}
            showWards
            theme={theme}
          />

          <div className="pointer-events-none absolute right-3 top-3 z-[400] flex max-w-[230px] flex-col items-end gap-1.5">
            <div className="pointer-events-auto rounded-md border border-line bg-surface/95 px-3 py-2 text-[11px] shadow-panel backdrop-blur-sm">
              <p className="tabular font-semibold text-ink">
                {formatNumber(points.data?.items.length ?? 0)} plotted
                {points.data ? ` of ${formatNumber(points.data.total)}` : ""}
              </p>
              <p className="mt-0.5 text-muted">
                {points.data?.scope === "ward" ? `Ward ${points.data.ward} scope` : "City-wide scope"}
              </p>
              {points.data?.truncated ? (
                <p className="mt-1 flex items-center gap-1 text-[color:var(--warning)]">
                  <TriangleAlert className="h-3 w-3" aria-hidden />
                  Highest priority 1,500 shown
                </p>
              ) : null}
            </div>
            {heat ? (
              <div className="pointer-events-auto rounded-md border border-line bg-surface/95 px-3 py-2 shadow-panel backdrop-blur-sm">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-faint">
                  Report density
                </p>
                <div className="flex items-center gap-2">
                  <span className="h-1.5 w-24 rounded-full" style={{ background: "linear-gradient(90deg, #9fd0d8, #1b526d, #a33a32)" }} aria-hidden />
                  <span className="text-[10px] text-muted">Low → High</span>
                </div>
              </div>
            ) : null}
            {forecastCategory ? (
              <div className="pointer-events-auto rounded-md border border-line bg-surface/95 px-3 py-2 shadow-panel backdrop-blur-sm">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-faint">
                  14-day forecast · {categoryMeta[forecastCategory].label}
                </p>
                <div className="flex items-center gap-2">
                  <span className="h-2.5 w-24 rounded-sm" style={{ background: "linear-gradient(90deg, transparent, #1b526d)" }} aria-hidden />
                  <span className="tabular text-[10px] text-muted">0 → {formatNumber(maxForecast)}</span>
                </div>
              </div>
            ) : null}
          </div>

          <div className="pointer-events-none absolute bottom-3 left-3 z-[400] rounded-md border border-line bg-surface/95 px-3 py-2 text-[11px] text-muted shadow-panel backdrop-blur-sm">
            <div className="flex flex-wrap items-center gap-3">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: "var(--primary)" }} aria-hidden />
                Open
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: "var(--positive)" }} aria-hidden />
                Resolved / closed
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full border border-line-strong" aria-hidden />
                Ward boundary
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
