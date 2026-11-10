import { useEffect, useState } from "react";
import { Bookmark, BookmarkPlus, RotateCcw, Search, X } from "lucide-react";
import { categories, statusMeta, statusOptions } from "../lib/meta";
import { activeFilterCount, type QueueFilters, type SavedFilter } from "../lib/savedFilters";
import type { Ward } from "../lib/types";

export function FilterBar({
  filters,
  wards,
  onChange,
  onReset,
  saved,
  onApplySaved,
  onDeleteSaved,
  onRequestSave,
  total,
}: {
  filters: QueueFilters;
  wards: Ward[];
  onChange: (patch: Partial<QueueFilters>) => void;
  onReset: () => void;
  saved: SavedFilter[];
  onApplySaved: (filter: SavedFilter) => void;
  onDeleteSaved: (id: string) => void;
  onRequestSave: () => void;
  total: number | undefined;
}) {
  const [search, setSearch] = useState(filters.q);
  const active = activeFilterCount(filters);

  useEffect(() => {
    setSearch(filters.q);
  }, [filters.q]);

  useEffect(() => {
    if (search === filters.q) return;
    const timer = window.setTimeout(() => onChange({ q: search }), 280);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className="card p-3">
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-[minmax(220px,1.6fr)_repeat(4,minmax(120px,1fr))]">
        <div>
          <label htmlFor="queue-search" className="label">
            Search
          </label>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint"
              aria-hidden
            />
            <input
              id="queue-search"
              type="search"
              className="field pl-8"
              placeholder="Title, description or address"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              autoComplete="off"
            />
          </div>
        </div>

        <div>
          <label htmlFor="queue-status" className="label">
            Status
          </label>
          <select
            id="queue-status"
            className="field"
            value={filters.status ?? ""}
            onChange={(event) =>
              onChange({ status: (event.target.value || null) as QueueFilters["status"] })
            }
          >
            <option value="">All statuses</option>
            {statusOptions.map((status) => (
              <option key={status} value={status}>
                {statusMeta[status].label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="queue-category" className="label">
            Category
          </label>
          <select
            id="queue-category"
            className="field"
            value={filters.category ?? ""}
            onChange={(event) =>
              onChange({ category: (event.target.value || null) as QueueFilters["category"] })
            }
          >
            <option value="">All categories</option>
            {categories.map((category) => (
              <option key={category} value={category}>
                {category.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase())}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="queue-ward" className="label">
            Ward
          </label>
          <select
            id="queue-ward"
            className="field"
            value={filters.ward ?? ""}
            onChange={(event) =>
              onChange({ ward: event.target.value ? Number(event.target.value) : null })
            }
          >
            <option value="">All wards</option>
            {wards.map((ward) => (
              <option key={ward.ward_no} value={ward.ward_no}>
                {ward.ward_no} · {ward.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="queue-sort" className="label">
            Sort
          </label>
          <select
            id="queue-sort"
            className="field"
            value={filters.sort}
            onChange={(event) => onChange({ sort: event.target.value as QueueFilters["sort"] })}
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="priority">Priority</option>
            <option value="due">Due soonest</option>
          </select>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-2.5">
        <span className="text-[11px] text-muted">
          {total === undefined ? "Loading results…" : `${total.toLocaleString("en-IN")} complaints`}
          {active ? ` · ${active} filter${active === 1 ? "" : "s"}` : ""}
        </span>

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {active ? (
            <button type="button" className="btn btn-ghost btn-sm" onClick={onReset}>
              <RotateCcw className="h-3 w-3" aria-hidden />
              Reset
            </button>
          ) : null}
          <button type="button" className="btn btn-secondary btn-sm" onClick={onRequestSave}>
            <BookmarkPlus className="h-3.5 w-3.5" aria-hidden />
            Save view
          </button>
        </div>
      </div>

      {saved.length > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-line pt-2.5">
          <Bookmark className="h-3.5 w-3.5 text-faint" aria-hidden />
          <span className="mr-1 text-[11px] text-faint">Saved views</span>
          {saved.map((filter) => (
            <span
              key={filter.id}
              className="inline-flex h-6 items-center overflow-hidden rounded border border-line bg-raised text-[11px] text-muted"
            >
              <button
                type="button"
                className="h-full px-2 hover:text-ink"
                onClick={() => onApplySaved(filter)}
              >
                {filter.name}
              </button>
              <button
                type="button"
                className="flex h-full w-6 items-center justify-center border-l border-line hover:bg-surface hover:text-[color:var(--critical)]"
                onClick={() => onDeleteSaved(filter.id)}
                aria-label={`Delete saved view ${filter.name}`}
              >
                <X className="h-3 w-3" aria-hidden />
              </button>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
