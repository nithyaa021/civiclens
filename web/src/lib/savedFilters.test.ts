import { describe, expect, it } from "vitest";
import {
  activeFilterCount,
  deleteFilter,
  filtersToSearch,
  loadSavedFilters,
  saveFilter,
  searchToFilters,
  type QueueFilters,
} from "./savedFilters";

class MemoryStorage implements Storage {
  private data = new Map<string, string>();

  get length(): number {
    return this.data.size;
  }

  clear(): void {
    this.data.clear();
  }

  getItem(key: string): string | null {
    return this.data.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.data.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.data.delete(key);
  }

  setItem(key: string, value: string): void {
    this.data.set(key, value);
  }
}

const filters: QueueFilters = {
  status: "in_progress",
  category: "drainage",
  ward: 7,
  q: "overflow",
  sort: "priority",
};

describe("saved queue filters", () => {
  it("round-trips filters through the URL", () => {
    const search = filtersToSearch(filters);
    expect(search.get("status")).toBe("in_progress");
    expect(search.get("category")).toBe("drainage");
    expect(search.get("ward")).toBe("7");
    expect(search.get("sort")).toBe("priority");
    expect(searchToFilters(search)).toEqual(filters);
  });

  it("defaults empty search params to an unfiltered newest view", () => {
    expect(searchToFilters(new URLSearchParams())).toEqual({
      status: null,
      category: null,
      ward: null,
      q: "",
      sort: "newest",
    });
  });

  it("counts active filters", () => {
    expect(activeFilterCount(filters)).toBe(5);
    expect(activeFilterCount({ ...filters, status: null, q: "" })).toBe(3);
    expect(activeFilterCount({ status: null, category: null, ward: null, q: "", sort: "newest" })).toBe(0);
  });

  it("stores, replaces by name and deletes saved views", () => {
    const storage = new MemoryStorage();
    saveFilter("Drainage", filters, storage, new Date("2026-11-10T09:00:00Z"));
    saveFilter("Everything", { ...filters, category: null }, storage, new Date("2026-11-10T09:01:00Z"));
    saveFilter("Drainage", { ...filters, ward: 9 }, storage, new Date("2026-11-10T09:02:00Z"));

    const loaded = loadSavedFilters(storage);
    expect(loaded).toHaveLength(2);
    expect(loaded[0].name).toBe("Drainage");
    expect(loaded[0].filters.ward).toBe(9);

    const remaining = deleteFilter(loaded[0].id, storage);
    expect(remaining.map((item) => item.name)).toEqual(["Everything"]);
  });

  it("ignores malformed storage payloads", () => {
    const storage = new MemoryStorage();
    storage.setItem("civiclens.savedFilters", "{not json");
    expect(loadSavedFilters(storage)).toEqual([]);
  });
});
