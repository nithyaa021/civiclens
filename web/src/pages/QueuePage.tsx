import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, RefreshCw, Tag, UserRoundCheck, X } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { usePageTitle } from "../lib/usePageTitle";
import { formatNumber } from "../lib/format";
import {
  activeFilterCount,
  deleteFilter,
  filtersToSearch,
  loadSavedFilters,
  saveFilter,
  searchToFilters,
  type QueueFilters,
  type SavedFilter,
} from "../lib/savedFilters";
import type { BulkResult, ComplaintStatus, SortKey } from "../lib/types";
import { ComplaintTable } from "../components/ComplaintTable";
import { Dialog } from "../components/Dialog";
import { FilterBar } from "../components/FilterBar";
import { EmptyState, ErrorState, PageHeader } from "../components/States";
import { Skeleton, TableSkeleton } from "../components/Skeleton";

const PAGE_SIZE = 25;
const BULK_STATUSES: { value: ComplaintStatus; label: string }[] = [
  { value: "assigned", label: "Assigned" },
  { value: "in_progress", label: "In progress" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
];

export function QueuePage() {
  const { user } = useAuth();
  const isStaff = user?.role === "admin" || user?.role === "ward_officer";
  usePageTitle(isStaff ? "Complaint queue" : "My complaints");
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => searchToFilters(searchParams), [searchParams]);
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saved, setSaved] = useState<SavedFilter[]>(() => loadSavedFilters());
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [officerId, setOfficerId] = useState("");
  const [bulkStatus, setBulkStatus] = useState<ComplaintStatus>("in_progress");
  const [bulkNote, setBulkNote] = useState("");
  const [result, setResult] = useState<{ text: string; failures: string[] } | null>(null);
  const queryClient = useQueryClient();

  const list = useQuery({
    queryKey: ["complaints", filters, page, user?.role],
    queryFn: () =>
      api.complaints({
        ...filters,
        page,
        page_size: PAGE_SIZE,
        // Citizens only ever see their own reports; staff see the ward/city.
        mine: user?.role === "citizen" ? true : undefined,
        ward: user?.role === "ward_officer" ? (filters.ward ?? user.ward) : filters.ward,
      }),
    placeholderData: (previous) => previous,
  });

  const wards = useQuery({ queryKey: ["wards"], queryFn: api.wards, staleTime: 120_000 });
  const officers = useQuery({
    queryKey: ["officers", user?.ward],
    queryFn: () => api.officers(user?.role === "ward_officer" ? (user.ward ?? undefined) : undefined),
    staleTime: 120_000,
    enabled: isStaff,
  });

  useEffect(() => {
    setSelected(new Set());
  }, [searchParams]);

  const update = (patch: Partial<QueueFilters>) => {
    const next = new URLSearchParams(filtersToSearch({ ...filters, ...patch }));
    setSearchParams(next, { replace: true });
  };

  const reset = () => {
    setSearchParams(new URLSearchParams(), { replace: true });
  };

  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1;
  const start = list.data && list.data.total > 0 ? (page - 1) * PAGE_SIZE + 1 : 0;
  const end = list.data ? Math.min(page * PAGE_SIZE, list.data.total) : 0;

  const toggle = (id: string) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    const items = list.data?.items ?? [];
    setSelected((previous) => {
      const allSelected = items.length > 0 && items.every((item) => previous.has(item.id));
      if (allSelected) return new Set();
      return new Set(items.map((item) => item.id));
    });
  };

  const afterBulk = (response: BulkResult, successText: string) => {
    void queryClient.invalidateQueries({ queryKey: ["complaints"] });
    void queryClient.invalidateQueries({ queryKey: ["overview"] });
    void queryClient.invalidateQueries({ queryKey: ["priority-open"] });
    setResult({
      text: `${successText} ${formatNumber(response.updated)} complaint${response.updated === 1 ? "" : "s"} updated.`,
      failures: response.failed.map(
        (failure) => `${failure.complaint_id.slice(-6).toUpperCase()}: ${failure.error}`,
      ),
    });
    setSelected(new Set());
    setAssignOpen(false);
    setStatusOpen(false);
    setBulkNote("");
  };

  const bulkAssign = useMutation({
    mutationFn: () => api.bulkAssign([...selected], officerId),
    onSuccess: (response) => {
      const officer = officers.data?.find((item) => item.id === officerId);
      afterBulk(response, `Assigned to ${officer?.full_name ?? "officer"} —`);
    },
  });

  const bulkUpdate = useMutation({
    mutationFn: () => api.bulkStatus([...selected], bulkStatus, bulkNote || undefined),
    onSuccess: (response) => {
      const label = BULK_STATUSES.find((item) => item.value === bulkStatus)?.label ?? bulkStatus;
      afterBulk(response, `Status set to ${label} —`);
    },
  });

  const mutationError = bulkAssign.error ?? bulkUpdate.error;

  const changeSort = (sort: SortKey) => update({ sort });

  return (
    <div className="mx-auto max-w-[1440px] space-y-4">
      <PageHeader
        eyebrow={isStaff ? "Case management" : "Your reports"}
        title={isStaff ? "Complaint queue" : "My complaints"}
        description={
          list.data
            ? `${formatNumber(list.data.total)} ${isStaff ? "reports in the current view" : "reports you filed"}${activeFilterCount(filters) ? " · filters applied" : ""}. ${isStaff ? "Select rows for bulk assignment or workflow updates." : "Open a case to follow its progress or confirm the fix."}`
            : isStaff
              ? "Review, prioritise and dispatch municipal complaints."
              : "Track everything you have reported and confirm when it is fixed."
        }
        actions={
          <div className="flex items-center gap-2">
            {!isStaff ? (
              <Link to="/public" className="btn btn-secondary btn-sm">
                Transparency portal
              </Link>
            ) : null}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => void list.refetch()}
              disabled={list.isFetching}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${list.isFetching ? "animate-spin" : ""}`} aria-hidden />
              Refresh
            </button>
          </div>
        }
      />

      <FilterBar
        filters={filters}
        wards={wards.data ?? []}
        onChange={update}
        onReset={reset}
        saved={saved}
        onApplySaved={(filter) => {
          setSearchParams(filtersToSearch(filter.filters), { replace: true });
        }}
        onDeleteSaved={(id) => setSaved(deleteFilter(id))}
        onRequestSave={() => {
          setSaveName("");
          setSaveOpen(true);
        }}
        total={list.data?.total}
      />

      {result ? (
        <div
          className="flex items-start gap-2 rounded-lg border border-[color:var(--positive-border)] bg-[color:var(--positive-soft)] px-3 py-2.5 text-[12px] text-ink"
          role="status"
        >
          <UserRoundCheck className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--positive)]" aria-hidden />
          <div className="min-w-0 flex-1">
            <p>{result.text}</p>
            {result.failures.length > 0 ? (
              <ul className="mt-1 list-disc pl-4 text-[11px] text-muted">
                {result.failures.map((failure) => (
                  <li key={failure}>{failure}</li>
                ))}
              </ul>
            ) : null}
          </div>
          <button
            type="button"
            className="btn btn-ghost h-6 w-6 px-0"
            onClick={() => setResult(null)}
            aria-label="Dismiss"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      ) : null}

      {mutationError ? (
        <div role="alert">
          <ErrorState
            error={mutationError}
            title="Bulk action did not complete"
            onRetry={() => {
              bulkAssign.reset();
              bulkUpdate.reset();
            }}
          />
        </div>
      ) : null}

      {isStaff && selected.size > 0 ? (
        <div
          className="sticky top-14 z-20 flex flex-wrap items-center gap-2 rounded-lg border border-[color:var(--primary)] bg-[color:var(--primary-soft)] px-3 py-2 shadow-panel"
          role="region"
          aria-label="Bulk actions"
        >
          <span className="tabular text-[12px] font-medium text-ink" aria-live="polite">
            {selected.size} selected
          </span>
          <span className="hidden text-[11px] text-muted sm:inline">
            Bulk changes are recorded in each complaint's audit trail.
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setOfficerId(officers.data?.find((item) => item.ward === user?.ward)?.id ?? "");
                setAssignOpen(true);
              }}
            >
              <UserRoundCheck className="h-3.5 w-3.5" aria-hidden />
              Assign
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setStatusOpen(true)}
            >
              <Tag className="h-3.5 w-3.5" aria-hidden />
              Update status
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setStatusOpen(false);
                setSelected(new Set());
              }}
            >
              Clear
            </button>
          </div>
        </div>
      ) : null}

      {list.isPending ? (
        <TableSkeleton rows={10} columns={7} />
      ) : list.isError ? (
        <ErrorState
          error={list.error}
          onRetry={() => void list.refetch()}
          title="Complaint queue unavailable"
        />
      ) : list.data.items.length === 0 ? (
        <div className="card">
          <EmptyState
            title={isStaff ? "No complaints match these filters" : "You have not reported anything here yet"}
            description={
              isStaff
                ? "Try a broader status, category or ward selection. Saved views can be reused from the filter bar."
                : "When you report an issue it appears here with its live status and resolution updates."
            }
            action={
              activeFilterCount(filters) > 0 ? (
                <button type="button" className="btn btn-secondary btn-sm" onClick={reset}>
                  Clear all filters
                </button>
              ) : undefined
            }
          />
        </div>
      ) : (
        <>
          <ComplaintTable
            items={list.data.items}
            selected={selected}
            onToggle={isStaff ? toggle : undefined}
            onToggleAll={isStaff ? toggleAll : undefined}
            sort={filters.sort}
            onSort={changeSort}
          />

          <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
            <p className="tabular text-[12px] text-muted">
              Showing {formatNumber(start)}–{formatNumber(end)} of {formatNumber(list.data.total)}
            </p>
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  next.set("page", String(page - 1));
                  setSearchParams(next);
                }}
                disabled={page <= 1}
              >
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
                Previous
              </button>
              <span className="tabular px-2 text-[12px] text-muted">
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  next.set("page", String(page + 1));
                  setSearchParams(next);
                }}
                disabled={page >= totalPages}
              >
                Next
                <ChevronRight className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          </div>
        </>
      )}

      <Dialog
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        title="Save this view"
        description="Saved views are stored in this browser and can be applied with one click."
        footer={
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setSaveOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!saveName.trim()}
              onClick={() => {
                setSaved(saveFilter(saveName, filters));
                setSaveOpen(false);
              }}
            >
              Save view
            </button>
          </>
        }
      >
        <label htmlFor="save-name" className="label">
          View name
        </label>
        <input
          id="save-name"
          className="field"
          maxLength={48}
          placeholder="e.g. Overdue drainage — Ward 7"
          value={saveName}
          onChange={(event) => setSaveName(event.target.value)}
        />
      </Dialog>

      <Dialog
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        title={`Assign ${selected.size} complaint${selected.size === 1 ? "" : "s"}`}
        description="The selected cases will move to the assigned queue for the officer below."
        footer={
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setAssignOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!officerId || bulkAssign.isPending}
              onClick={() => bulkAssign.mutate()}
            >
              {bulkAssign.isPending ? "Assigning…" : "Assign cases"}
            </button>
          </>
        }
      >
        {officers.isError ? (
          <ErrorState error={officers.error} onRetry={() => void officers.refetch()} title="Officer directory unavailable" />
        ) : officers.isPending ? (
          <Skeleton className="h-[34px] w-full" />
        ) : (
          <>
            <label htmlFor="officer" className="label">
              Ward officer
            </label>
            <select
              id="officer"
              className="field"
              value={officerId}
              onChange={(event) => setOfficerId(event.target.value)}
            >
              <option value="">Select an officer</option>
              {(officers.data ?? []).map((officer) => (
                <option key={officer.id} value={officer.id}>
                  {officer.full_name} · Ward {officer.ward ?? "—"}
                </option>
              ))}
            </select>
            <p className="mt-2 text-[11px] leading-5 text-muted">
              An audit event and a notification are created for every case. Officer workload is not
              limited by this action.
            </p>
          </>
        )}
      </Dialog>

      <Dialog
        open={statusOpen}
        onClose={() => setStatusOpen(false)}
        title={`Update ${selected.size} complaint${selected.size === 1 ? "" : "s"}`}
        description="Only transitions permitted by the workflow will be accepted. Failed cases are reported individually."
        footer={
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setStatusOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={bulkUpdate.isPending}
              onClick={() => bulkUpdate.mutate()}
            >
              {bulkUpdate.isPending ? "Updating…" : "Apply status"}
            </button>
          </>
        }
      >
        <label htmlFor="bulk-status" className="label">
          New status
        </label>
        <select
          id="bulk-status"
          className="field"
          value={bulkStatus}
          onChange={(event) => setBulkStatus(event.target.value as ComplaintStatus)}
        >
          {BULK_STATUSES.map((status) => (
            <option key={status.value} value={status.value}>
              {status.label}
            </option>
          ))}
        </select>
        <label htmlFor="bulk-note" className="label mt-3">
          Note for the audit trail <span className="font-normal text-faint">(optional)</span>
        </label>
        <textarea
          id="bulk-note"
          className="field-textarea"
          maxLength={500}
          placeholder="Reason, crew reference or dispatch instruction"
          value={bulkNote}
          onChange={(event) => setBulkNote(event.target.value)}
        />
      </Dialog>
    </div>
  );
}
