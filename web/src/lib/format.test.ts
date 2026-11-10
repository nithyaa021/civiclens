import { describe, expect, it } from "vitest";
import {
  ageDays,
  formatDays,
  formatNumber,
  formatPercent,
  shortId,
  slaDeadline,
  titleCase,
} from "./format";

describe("format helpers", () => {
  it("formats Indian-grouped numbers", () => {
    expect(formatNumber(1915)).toBe("1,915");
    expect(formatNumber(1250000)).toBe("12,50,000");
    expect(formatNumber(null)).toBe("—");
  });

  it("formats ratios as percentages", () => {
    expect(formatPercent(0.9373, 1)).toBe("93.7%");
    expect(formatPercent(null)).toBe("—");
  });

  it("formats durations in hours below one day", () => {
    expect(formatDays(0.5)).toBe("12h");
    expect(formatDays(3.04)).toBe("3.0d");
    expect(formatDays(null)).toBe("—");
  });

  it("derives SLA labels from the due time", () => {
    const now = new Date("2026-11-10T10:00:00Z");
    expect(slaDeadline("2026-11-10T08:00:00Z", "in_progress", now)).toMatchObject({
      tone: "critical",
      label: "2h overdue",
    });
    expect(slaDeadline("2026-11-10T14:00:00Z", "assigned", now).tone).toBe("warning");
    expect(slaDeadline("2026-11-12T10:00:00Z", "assigned", now).tone).toBe("neutral");
    expect(slaDeadline(null, "closed", now)).toMatchObject({ tone: "done", label: "Met" });
  });

  it("counts calendar age in whole days", () => {
    expect(ageDays("2026-11-01T09:00:00Z", new Date("2026-11-10T10:00:00Z"))).toBe(9);
  });

  it("normalises enum values for display", () => {
    expect(titleCase("in_progress")).toBe("In Progress");
    expect(shortId("665f1c2e9b0d4a2f18c3ab71")).toBe("C3AB71");
  });
});
