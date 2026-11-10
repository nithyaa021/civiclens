import { Link } from "react-router-dom";
import { ChevronDown, ChevronUp } from "lucide-react";
import { CategoryLabel, SeverityBadge, SlaChip, StatusBadge } from "./Badges";
import { formatNumber, relativeTime, shortId } from "../lib/format";
import type { Complaint, SortKey } from "../lib/types";

const COLUMNS: { key: string; label: string; sort?: SortKey; className?: string }[] = [
  { key: "id", label: "ID", className: "w-[74px]" },
  { key: "complaint", label: "Complaint", className: "min-w-[280px]" },
  { key: "category", label: "Category", className: "w-[150px]" },
  { key: "status", label: "Status", className: "w-[124px]" },
  { key: "priority", label: "Priority", sort: "priority", className: "w-[92px]" },
  { key: "sla", label: "SLA", className: "w-[116px]" },
  { key: "ward", label: "Ward", className: "w-[64px]" },
  { key: "created", label: "Reported", sort: "newest", className: "w-[104px]" },
];

export function ComplaintTable({
  items,
  selected,
  onToggle,
  onToggleAll,
  sort,
  onSort,
}: {
  items: Complaint[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  sort: SortKey;
  onSort: (sort: SortKey) => void;
}) {
  const allSelected = items.length > 0 && items.every((item) => selected.has(item.id));
  const someSelected = items.some((item) => selected.has(item.id));

  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="data-table min-w-[900px]">
        <caption className="sr-only">
          Complaint queue. Use the checkboxes to select rows for bulk actions.
        </caption>
        <thead>
          <tr>
            <th className="w-9 pl-3">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 rounded border-line-strong accent-[color:var(--primary)]"
                checked={allSelected}
                ref={(element) => {
                  if (element) element.indeterminate = !allSelected && someSelected;
                }}
                onChange={onToggleAll}
                aria-label={allSelected ? "Deselect all rows" : "Select all rows on this page"}
              />
            </th>
            {COLUMNS.map((column) => (
              <th
                key={column.key}
                className={column.className}
                aria-sort={
                  column.sort === sort
                    ? sort === "oldest"
                      ? "ascending"
                      : "descending"
                    : undefined
                }
              >
                {column.sort ? (
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 uppercase tracking-[0.06em] hover:text-ink"
                    onClick={() => {
                      if (!column.sort) return;
                      if (column.key === "created") {
                        onSort(sort === "newest" ? "oldest" : "newest");
                      } else {
                        onSort(column.sort);
                      }
                    }}
                  >
                    {column.label}
                    {column.sort === sort || (column.key === "created" && (sort === "newest" || sort === "oldest")) ? (
                      sort === "oldest" ? (
                        <ChevronUp className="h-3 w-3" aria-hidden />
                      ) : (
                        <ChevronDown className="h-3 w-3" aria-hidden />
                      )
                    ) : null}
                  </button>
                ) : (
                  column.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((complaint) => {
            const checked = selected.has(complaint.id);
            return (
              <tr
                key={complaint.id}
                style={checked ? { background: "var(--primary-soft)" } : undefined}
                data-selected={checked || undefined}
              >
                <td className="pl-3">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 rounded border-line-strong accent-[color:var(--primary)]"
                    checked={checked}
                    onChange={() => onToggle(complaint.id)}
                    aria-label={`Select complaint ${shortId(complaint.id)}`}
                  />
                </td>
                <td className="tabular text-[11px] text-faint">
                  <Link
                    to={`/queue/${complaint.id}`}
                    className="hover:text-primary hover:underline"
                  >
                    {shortId(complaint.id)}
                  </Link>
                </td>
                <td>
                  <Link to={`/queue/${complaint.id}`} className="group block min-w-0">
                    <span className="flex items-center gap-2">
                      <span className="truncate font-medium text-ink group-hover:text-primary">
                        {complaint.title}
                      </span>
                      <SeverityBadge severity={complaint.severity} />
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-muted">
                      {complaint.address}
                      {complaint.votes > 0 ? ` · ${formatNumber(complaint.votes)} supports` : ""}
                    </span>
                  </Link>
                </td>
                <td>
                  <CategoryLabel category={complaint.category} className="text-[12px]" />
                </td>
                <td>
                  <StatusBadge status={complaint.status} />
                </td>
                <td>
                  <div className="flex items-center gap-1.5">
                    <span
                      className="tabular text-[12px] font-medium text-ink"
                      title={`Priority score ${complaint.priority?.score ?? 0} of 100`}
                    >
                      {complaint.priority ? Math.round(complaint.priority.score) : "—"}
                    </span>
                    <span className="h-1 w-8 overflow-hidden rounded-full bg-raised" aria-hidden>
                      <span
                        className="block h-full rounded-full"
                        style={{
                          width: `${Math.min(100, complaint.priority?.score ?? 0)}%`,
                          background:
                            (complaint.priority?.score ?? 0) >= 70
                              ? "var(--critical)"
                              : (complaint.priority?.score ?? 0) >= 45
                                ? "var(--warning)"
                                : "var(--primary)",
                        }}
                      />
                    </span>
                  </div>
                </td>
                <td>
                  <SlaChip sla={complaint.sla} status={complaint.status} />
                </td>
                <td className="tabular text-[12px] text-muted">
                  {complaint.ward ?? "—"}
                </td>
                <td className="whitespace-nowrap text-[11px] text-muted">
                  {relativeTime(complaint.created_at)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
