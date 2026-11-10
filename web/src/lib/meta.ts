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
  roads: { label: "Roads", short: "Roads", icon: Route, className: "text-[#67552e]" },
  drainage: { label: "Drainage", short: "Drainage", icon: Waves, className: "text-[#2f6470]" },
  water_supply: { label: "Water supply", short: "Water", icon: Droplets, className: "text-[#2e5f8a]" },
  sanitation: { label: "Sanitation", short: "Sanitation", icon: Wrench, className: "text-[#5d5b47]" },
  waste_management: {
    label: "Waste management",
    short: "Waste",
    icon: Trash2,
    className: "text-[#5a6640]",
  },
  streetlight: { label: "Street lighting", short: "Lighting", icon: Lightbulb, className: "text-[#7b6123]" },
  traffic_signal: {
    label: "Traffic signals",
    short: "Signals",
    icon: TrafficCone,
    className: "text-[#7a4b3a]",
  },
  noise: { label: "Noise", short: "Noise", icon: Volume2, className: "text-[#5b5a72]" },
  parks_trees: { label: "Parks & trees", short: "Parks", icon: Trees, className: "text-[#386346]" },
  other: { label: "Other", short: "Other", icon: CircleHelp, className: "text-[#5d6669]" },
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
    dot: "bg-[#2c5f8a]",
    className: "border-[#c9d9e7] bg-[#eaf1f8] text-[#224c70]",
  },
  assigned: {
    label: "Assigned",
    dot: "bg-[#6b5b95]",
    className: "border-[#d9d2e9] bg-[#f1eef8] text-[#544677]",
  },
  in_progress: {
    label: "In progress",
    dot: "bg-[#94620f]",
    className: "border-[#ead9b7] bg-[#fbf1dd] text-[#7c520c]",
  },
  resolved: {
    label: "Resolved",
    dot: "bg-[#1f7a4d]",
    className: "border-[#c5e2d3] bg-[#e8f4ed] text-[#19643f]",
  },
  closed: {
    label: "Closed",
    dot: "bg-[#5b6b72]",
    className: "border-[#d8dee0] bg-[#f2f4f5] text-[#4a585e]",
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
