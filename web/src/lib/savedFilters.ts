import type { ComplaintCategory, ComplaintStatus, SortKey } from "./types";

export interface QueueFilters {
  status: ComplaintStatus | null;
  category: ComplaintCategory | null;
  ward: number | null;
  q: string;
  sort: SortKey;
}

export interface SavedFilter {
  id: string;
  name: string;
  filters: QueueFilters;
  createdAt: string;
}

const STORAGE_KEY = "civiclens.savedFilters";
const MAX_SAVED = 12;

function storageOrDefault(storage?: Storage): Storage | null {
  if (storage) return storage;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function loadSavedFilters(storage?: Storage): SavedFilter[] {
  const store = storageOrDefault(storage);
  if (!store) return [];
  try {
    const raw = store.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as SavedFilter[];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item) =>
        typeof item?.id === "string" &&
        typeof item?.name === "string" &&
        item.filters !== undefined,
    );
  } catch {
    return [];
  }
}

export function saveFilter(
  name: string,
  filters: QueueFilters,
  storage?: Storage,
  now = new Date(),
): SavedFilter[] {
  const store = storageOrDefault(storage);
  const existing = loadSavedFilters(storage);
  const cleaned = name.trim();
  if (!store || !cleaned) return existing;
  const entry: SavedFilter = {
    id: `filter-${now.getTime()}`,
    name: cleaned.slice(0, 48),
    filters,
    createdAt: now.toISOString(),
  };
  const next = [entry, ...existing.filter((item) => item.name !== entry.name)].slice(
    0,
    MAX_SAVED,
  );
  try {
    store.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    return existing;
  }
  return next;
}

export function deleteFilter(id: string, storage?: Storage): SavedFilter[] {
  const store = storageOrDefault(storage);
  if (!store) return [];
  const next = loadSavedFilters(storage).filter((item) => item.id !== id);
  try {
    store.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    return loadSavedFilters(storage);
  }
  return next;
}

export function filtersToSearch(filters: QueueFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.category) params.set("category", filters.category);
  if (filters.ward) params.set("ward", String(filters.ward));
  if (filters.q) params.set("q", filters.q);
  if (filters.sort !== "newest") params.set("sort", filters.sort);
  return params;
}

export function searchToFilters(params: URLSearchParams): QueueFilters {
  const status = params.get("status");
  const category = params.get("category");
  const ward = Number(params.get("ward"));
  const sort = params.get("sort");
  return {
    status: status ? (status as ComplaintStatus) : null,
    category: category ? (category as ComplaintCategory) : null,
    ward: Number.isFinite(ward) && ward > 0 ? ward : null,
    q: params.get("q") ?? "",
    sort:
      sort === "oldest" || sort === "priority" || sort === "due"
        ? (sort as SortKey)
        : "newest",
  };
}

export function activeFilterCount(filters: QueueFilters): number {
  let count = 0;
  if (filters.status) count += 1;
  if (filters.category) count += 1;
  if (filters.ward) count += 1;
  if (filters.q.trim()) count += 1;
  if (filters.sort !== "newest") count += 1;
  return count;
}
