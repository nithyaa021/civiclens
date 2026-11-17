import {
  CircleHelp,
  Droplets,
  Lightbulb,
  Route,
  TrafficCone,
  Trash2,
  Trees,
  Volume2,
  Waves,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { ComplaintCategory, ComplaintStatus } from "./types";

export interface CategoryMeta {
  label: string;
  short: string;
  icon: LucideIcon;
  className: string;
}

export const categoryMeta: Record<ComplaintCategory, CategoryMeta> = {
  roads: { label: "Roads", short: "Roads", icon: Route, className: "text-[color:var(--cat-roads)]" },
  drainage: { label: "Drainage", short: "Drainage", icon: Waves, className: "text-[color:var(--cat-drainage)]" },
  water_supply: {
    label: "Water supply",
    short: "Water",
    icon: Droplets,
    className: "text-[color:var(--cat-water)]",
  },
  sanitation: {
    label: "Sanitation",
    short: "Sanitation",
    icon: Wrench,
    className: "text-[color:var(--cat-sanitation)]",
  },
  waste_management: {
    label: "Waste management",
    short: "Waste",
    icon: Trash2,
    className: "text-[color:var(--cat-waste)]",
  },
  streetlight: {
    label: "Street lighting",
    short: "Lighting",
    icon: Lightbulb,
    className: "text-[color:var(--cat-lighting)]",
  },
  traffic_signal: {
    label: "Traffic signals",
    short: "Signals",
    icon: TrafficCone,
    className: "text-[color:var(--cat-traffic)]",
  },
  noise: { label: "Noise", short: "Noise", icon: Volume2, className: "text-[color:var(--cat-noise)]" },
  parks_trees: {
    label: "Parks & trees",
    short: "Parks",
    icon: Trees,
    className: "text-[color:var(--cat-parks)]",
  },
  other: { label: "Other", short: "Other", icon: CircleHelp, className: "text-[color:var(--cat-other)]" },
};

export const categories = Object.keys(categoryMeta) as ComplaintCategory[];

export interface StatusMeta {
  label: string;
  dot: string;
  className: string;
}

export const statusMeta: Record<ComplaintStatus, StatusMeta> = {
  submitted: {
    label: "Submitted",
    dot: "bg-[color:var(--info)]",
    className:
      "border-[color:var(--info-border)] bg-[color:var(--info-soft)] text-[color:var(--info)]",
  },
  assigned: {
    label: "Assigned",
    dot: "bg-[color:var(--aurora-4)]",
    className:
      "border-[color:var(--primary-soft)] bg-[color:var(--primary-soft)] text-[color:var(--primary)]",
  },
  in_progress: {
    label: "In progress",
    dot: "bg-[color:var(--warning)]",
    className:
      "border-[color:var(--warning-border)] bg-[color:var(--warning-soft)] text-[color:var(--warning)]",
  },
  resolved: {
    label: "Resolved",
    dot: "bg-[color:var(--positive)]",
    className:
      "border-[color:var(--positive-border)] bg-[color:var(--positive-soft)] text-[color:var(--positive)]",
  },
  closed: {
    label: "Closed",
    dot: "bg-[color:var(--faint)]",
    className: "border-line bg-raised text-muted",
  },
};

export const statusOptions = Object.keys(statusMeta) as ComplaintStatus[];

export const severityLabel: Record<number, string> = {
  1: "Minor",
  2: "Low",
  3: "Moderate",
  4: "High",
  5: "Critical",
};

export const statusTransitions: Record<ComplaintStatus, ComplaintStatus[]> = {
  submitted: ["assigned"],
  assigned: ["in_progress", "submitted"],
  in_progress: ["resolved", "assigned"],
  resolved: ["closed", "in_progress"],
  closed: ["submitted"],
};

export const statusActionLabel: Record<ComplaintStatus, string> = {
  submitted: "Reopen as submitted",
  assigned: "Mark assigned",
  in_progress: "Start work",
  resolved: "Submit resolution",
  closed: "Close case",
};
