import { differenceInCalendarDays, differenceInHours, format, formatDistanceToNowStrict } from "date-fns";

export const number = new Intl.NumberFormat("en-IN");

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return number.format(value);
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatDays(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1) return `${Math.max(1, Math.round(value * 24))}h`;
  return `${value.toFixed(1)}d`;
}

export function relativeTime(iso: string, now = new Date()): string {
  const date = new Date(iso);
  const hours = Math.abs(differenceInHours(now, date));
  if (hours < 1) {
    const minutes = Math.max(1, Math.round((now.getTime() - date.getTime()) / 60000));
    return `${minutes}m ago`;
  }
  if (hours < 48) return `${Math.round(hours)}h ago`;
  return `${formatDistanceToNowStrict(date, { addSuffix: true })}`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return format(new Date(iso), "d MMM yyyy, HH:mm");
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return format(new Date(iso), "d MMM yyyy");
}

export function formatDay(iso: string): string {
  return format(new Date(iso), "d MMM");
}

export function ageDays(iso: string, now = new Date()): number {
  return Math.max(0, differenceInCalendarDays(now, new Date(iso)));
}

export type DeadlineTone = "neutral" | "warning" | "critical" | "done";

export interface Deadline {
  label: string;
  tone: DeadlineTone;
  hours: number;
}

export function slaDeadline(dueAt: string | null, status: string, now = new Date()): Deadline {
  if (status === "resolved" || status === "closed") {
    return { label: "Met", tone: "done", hours: 0 };
  }
  if (!dueAt) return { label: "No clock", tone: "neutral", hours: 0 };
  const diffHours = (new Date(dueAt).getTime() - now.getTime()) / 3_600_000;
  if (diffHours < 0) {
    const overdue = Math.abs(diffHours);
    return {
      label: overdue >= 48 ? `${Math.round(overdue / 24)}d overdue` : `${Math.round(overdue)}h overdue`,
      tone: "critical",
      hours: diffHours,
    };
  }
  if (diffHours < 24) {
    return { label: `${Math.max(1, Math.round(diffHours))}h left`, tone: "warning", hours: diffHours };
  }
  return { label: `${Math.round(diffHours / 24)}d left`, tone: "neutral", hours: diffHours };
}

export function titleCase(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function shortId(id: string): string {
  return id.slice(-6).toUpperCase();
}

export function plural(value: number, singular: string, pluralWord = `${singular}s`): string {
  return `${formatNumber(value)} ${value === 1 ? singular : pluralWord}`;
}
