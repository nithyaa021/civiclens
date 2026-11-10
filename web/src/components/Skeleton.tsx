import type { CSSProperties } from "react";
import { clsx } from "clsx";

export function Skeleton({ className, style }: { className?: string; style?: CSSProperties }) {
  return <div className={clsx("skeleton", className)} style={style} aria-hidden />;
}

export function SkeletonLines({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={clsx("space-y-2", className)} aria-hidden>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          className={clsx("h-3", index === lines - 1 ? "w-2/3" : "w-full")}
        />
      ))}
    </div>
  );
}

export function KpiSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2 xl:grid-cols-5">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="bg-surface p-4">
          <Skeleton className="mb-3 h-3 w-24" />
          <Skeleton className="mb-3 h-7 w-16" />
          <Skeleton className="h-3 w-20" />
        </div>
      ))}
    </div>
  );
}

export function ChartSkeleton({ height = 240 }: { height?: number }) {
  return (
    <div className="card p-4" aria-hidden>
      <Skeleton className="mb-4 h-3 w-32" />
      <div className="flex items-end gap-2" style={{ height }} aria-hidden>
        {[42, 58, 36, 71, 52, 64, 47, 83, 61, 55, 74, 48, 66, 39].map((value, index) => (
          <Skeleton key={index} className="flex-1" style={{ height: `${value}%` }} />
        ))}
      </div>
    </div>
  );
}

export function TableSkeleton({ rows = 8, columns = 6 }: { rows?: number; columns?: number }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface" aria-hidden>
      <div className="flex gap-4 border-b border-line bg-raised px-4 py-2.5">
        {Array.from({ length: columns }).map((_, index) => (
          <Skeleton key={index} className="h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, row) => (
        <div key={row} className="flex items-center gap-4 border-b border-line px-4 py-3 last:border-b-0">
          {Array.from({ length: columns }).map((_, column) => (
            <Skeleton
              key={column}
              className={clsx("h-3", column === 1 ? "flex-[3]" : "flex-1")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
