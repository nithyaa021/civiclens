import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatDay, formatNumber } from "../lib/format";
import type { TrendPoint } from "../lib/types";

function TrendTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number; color?: string }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-[11px] shadow-pop">
      <p className="mb-1 font-medium text-ink">{label}</p>
      {payload.map((item) => (
        <p key={item.name} className="tabular flex items-center gap-1.5 text-muted">
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: item.color }}
            aria-hidden
          />
          <span className="capitalize">{item.name}</span>
          <span className="ml-auto font-medium text-ink">{formatNumber(item.value ?? 0)}</span>
        </p>
      ))}
    </div>
  );
}

export function TrendChart({ points }: { points: TrendPoint[] }) {
  const data = points.map((point) => ({
    label: formatDay(point.date),
    received: point.received,
    resolved: point.resolved,
  }));
  const totalReceived = points.reduce((sum, point) => sum + point.received, 0);
  const totalResolved = points.reduce((sum, point) => sum + point.resolved, 0);

  return (
    <div className="card flex h-full flex-col p-4">
      <div className="mb-1 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="section-title">Received vs resolved</h2>
          <p className="mt-0.5 text-[11px] text-muted">Daily volume across the reporting window</p>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-muted">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-primary" aria-hidden />
            Received
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[color:var(--positive)]" aria-hidden />
            Resolved
          </span>
        </div>
      </div>

      <p className="sr-only">
        {formatNumber(totalReceived)} complaints received and {formatNumber(totalResolved)}{" "}
        resolved over the displayed period.
      </p>

      <div
        className="mt-3 min-h-[220px] flex-1"
        role="img"
        aria-label={`Trend chart: ${totalReceived} received and ${totalResolved} resolved over ${points.length} days.`}
      >
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={data} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
            <defs>
              <linearGradient id="receivedFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.16} />
                <stop offset="100%" stopColor="var(--primary)" stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} strokeDasharray="2 3" />
            <XAxis
              dataKey="label"
              tick={{ fill: "var(--faint)", fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: "var(--line)" }}
              interval={Math.max(0, Math.floor(data.length / 6) - 1)}
              minTickGap={18}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fill: "var(--faint)", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={44}
            />
            <Tooltip content={<TrendTooltip />} cursor={{ stroke: "var(--line-strong)", strokeWidth: 1 }} />
            <Area
              type="monotone"
              dataKey="received"
              stroke="var(--primary)"
              strokeWidth={1.8}
              fill="url(#receivedFill)"
              dot={false}
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
            <Line
              type="monotone"
              dataKey="resolved"
              stroke="var(--positive)"
              strokeWidth={1.6}
              dot={false}
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-2 flex items-center justify-between border-t border-line pt-2.5 text-[11px] text-muted">
        <span>
          Received <span className="tabular font-medium text-ink">{formatNumber(totalReceived)}</span>
        </span>
        <span>
          Resolved <span className="tabular font-medium text-ink">{formatNumber(totalResolved)}</span>
        </span>
      </div>
    </div>
  );
}
