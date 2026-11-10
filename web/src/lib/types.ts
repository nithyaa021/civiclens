export type Role = "citizen" | "ward_officer" | "admin";
export type ComplaintStatus =
  | "submitted"
  | "assigned"
  | "in_progress"
  | "resolved"
  | "closed";
export type ComplaintCategory =
  | "roads"
  | "drainage"
  | "water_supply"
  | "sanitation"
  | "waste_management"
  | "streetlight"
  | "traffic_signal"
  | "noise"
  | "parks_trees"
  | "other";
export type SortKey = "newest" | "oldest" | "priority" | "due";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  ward: number | null;
  status: "active" | "inactive";
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface GeoPoint {
  type: "Point";
  coordinates: [number, number];
}

export interface GeoPolygon {
  type: "Polygon";
  coordinates: [number, number][][];
}

export interface Attachment {
  id: string;
  kind: "before" | "after" | "general";
  content_type: string;
  created_at: string;
}

export interface LanguageInfo {
  code: string;
  name: string;
  confidence: number;
  method: string;
}

export interface MlSuggestion {
  predicted: ComplaintCategory;
  confidence: number;
  top: [ComplaintCategory, number][];
  model_version: string;
}

export interface PriorityComponent {
  raw: number;
  normalized: number;
  weight: number;
  contribution: number;
}

export interface PriorityScore {
  score: number;
  components: Record<string, PriorityComponent>;
  formula: string;
  computed_at: string;
}

export interface SlaState {
  target_hours: number;
  due_at: string;
  breached: boolean;
  breach_count: number;
  escalation_level: number;
  escalation_rung: string | null;
  escalated_at: string | null;
  last_breach_at: string | null;
}

export interface ResolutionVerification {
  after_media_id: string;
  confidence: number;
  passed: boolean;
  features: Record<string, number>;
  model_version: string;
  note: string | null;
  verified_at: string;
}

export interface ResolutionRecord {
  after_media_id: string;
  officer_id: string | null;
  note: string | null;
  verification: ResolutionVerification | null;
  citizen_decision: "confirmed" | "disputed" | null;
  decision_note: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface Complaint {
  id: string;
  title: string;
  description: string;
  category: ComplaintCategory;
  severity: number;
  location: GeoPoint;
  address: string;
  landmark: string | null;
  status: ComplaintStatus;
  ward: number | null;
  citizen_id: string | null;
  assigned_officer_id: string | null;
  votes: number;
  duplicate_of: string | null;
  language: LanguageInfo | null;
  english_translation: string | null;
  category_ml: MlSuggestion | null;
  enrichment: "pending" | "running" | "done" | "failed";
  priority: PriorityScore | null;
  sla: SlaState | null;
  resolution: ResolutionRecord | null;
  cluster_id: string | null;
  attachments: Attachment[];
  created_at: string;
  updated_at: string;
}

export interface AuditEvent {
  id: string;
  action: string;
  complaint_id: string | null;
  actor_id: string | null;
  actor_role: string | null;
  details: Record<string, unknown>;
  at: string;
}

export interface AuditPage {
  items: AuditEvent[];
  total: number;
}

export interface InternalNote {
  id: string;
  complaint_id: string;
  author_id: string;
  author_name: string;
  author_role: string;
  note: string;
  created_at: string;
}

export interface InternalNoteList {
  items: InternalNote[];
  total: number;
}

export interface SimilarIssue {
  complaint: {
    id: string;
    title: string;
    category: ComplaintCategory;
    status: ComplaintStatus;
    severity: number;
    ward: number | null;
    votes: number;
    location: GeoPoint;
    address: string;
    created_at: string;
  };
  score: number;
  distance_km: number | null;
}

export interface SimilarIssueResponse {
  items: SimilarIssue[];
  query_language: LanguageInfo | null;
  min_score: number;
}

export interface KpiSummary {
  open: number;
  resolved_this_week: number;
  avg_resolution_days: number | null;
  sla_breaches: number;
  total: number;
  resolved_rate: number;
}

export interface TrendPoint {
  date: string;
  received: number;
  resolved: number;
}

export interface CategoryStat {
  category: ComplaintCategory;
  count: number;
  open: number;
  resolved: number;
  share: number;
}

export interface Overview {
  generated_at: string;
  period_days: number;
  scope: "all" | "ward";
  ward: number | null;
  kpis: KpiSummary;
  trend: TrendPoint[];
  categories: CategoryStat[];
}

export interface MapComplaint {
  id: string;
  title: string;
  category: ComplaintCategory;
  status: ComplaintStatus;
  severity: number;
  ward: number | null;
  priority: number | null;
  location: GeoPoint;
  created_at: string;
  due_at: string | null;
}

export interface ComplaintMapResponse {
  items: MapComplaint[];
  total: number;
  truncated: boolean;
  scope: "all" | "ward";
  ward: number | null;
}

export interface Ward {
  ward_no: number;
  name: string;
  zone: string;
  centroid: GeoPoint;
  geometry: GeoPolygon;
  sensitive_locations: {
    kind: "school" | "hospital";
    name: string;
    location: GeoPoint;
  }[];
  complaint_count: number;
}

export interface Officer {
  id: string;
  full_name: string;
  ward: number | null;
}

export interface Cluster {
  id: string;
  category: ComplaintCategory;
  count: number;
  open_count: number;
  first_reported: string;
  last_reported: string;
  affected_area: {
    centroid: GeoPoint;
    radius_km: number;
    bbox: [[number, number], [number, number]];
  };
  dominant_ward: number | null;
  complaint_ids: string[];
  trend: number[];
  computed_at: string;
}

export interface ClusterResponse {
  items: Cluster[];
  lookback_days: number;
  computed_at: string;
}

export interface WardForecastSummary {
  ward: number;
  total_predicted: number;
  peak_day: string | null;
  peak_predicted: number;
}

export interface ForecastMap {
  category: ComplaintCategory;
  horizon_days: number;
  items: WardForecastSummary[];
  generated_at: string;
}

export interface AssistantCitation {
  complaint_id: string;
  title: string;
  status: ComplaintStatus;
  category: ComplaintCategory;
}

export interface AssistantResponse {
  answer: string;
  intent: string;
  scope: string;
  citations: AssistantCitation[];
  clarification: string | null;
}

export interface PublicWardStat {
  ward: number;
  name: string;
  zone: string;
  total: number;
  open: number;
  resolved: number;
  avg_resolution_days: number | null;
  sla_compliance: number;
  resolved_rate: number;
}

export interface PublicCategoryStat {
  category: ComplaintCategory;
  total: number;
  resolved: number;
  share: number;
}

export interface PublicResolution {
  title: string;
  category: ComplaintCategory;
  ward: number | null;
  ward_name: string | null;
  resolved_at: string;
  resolution_days: number | null;
  verified: boolean;
}

export interface PublicStats {
  generated_at: string;
  period_days: number;
  generated_for: string;
  totals: KpiSummary;
  resolved_in_period: number;
  wards: PublicWardStat[];
  categories: PublicCategoryStat[];
  recent_resolutions: PublicResolution[];
}

export interface BulkResult {
  updated: number;
  items: Complaint[];
  failed: { complaint_id: string; error: string }[];
}
