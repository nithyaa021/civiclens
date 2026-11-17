import type {
  AssistantResponse,
  AuditPage,
  BulkResult,
  ClusterResponse,
  Complaint,
  ComplaintCategory,
  ComplaintMapResponse,
  ComplaintStatus,
  ForecastMap,
  InternalNote,
  InternalNoteList,
  Officer,
  Overview,
  Page,
  PublicStats,
  SimilarIssueResponse,
  SortKey,
  TokenPair,
  User,
  Ward,
} from "./types";

const TOKEN_KEY = "civiclens.tokens";

// In development the Vite proxy forwards `/api` to the local API, so an empty
// base keeps requests same-origin.  In production (Vercel + Oracle VM) set
// `VITE_API_BASE_URL` to the deployed API origin, e.g. https://api.203.0.113.10.sslip.io
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const API_ROOT = `${API_BASE}/api/v1`;

/** Swagger UI for the deployed API (same origin in local dev). */
export const apiDocsUrl = `${API_BASE}/docs`;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | undefined;

  constructor(
    status: number,
    message: string,
    code = "request_failed",
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export interface MeResponse {
  user: User;
  role: User["role"];
}

export interface DemoPerspective {
  id: string;
  label: string;
  role: User["role"];
  ward: number | null;
  description: string;
}

export interface DemoDirectory {
  enabled: boolean;
  default: string | null;
  perspectives: DemoPerspective[];
}

function readTokens(): TokenPair | null {
  try {
    const raw = window.localStorage.getItem(TOKEN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as TokenPair;
    return parsed.access_token && parsed.refresh_token ? parsed : null;
  } catch {
    return null;
  }
}

let tokens: TokenPair | null = typeof window === "undefined" ? null : readTokens();
const listeners = new Set<(next: TokenPair | null) => void>();

function emit(): void {
  for (const listener of listeners) listener(tokens);
}

export const authStore = {
  get(): TokenPair | null {
    return tokens;
  },
  set(next: TokenPair | null): void {
    tokens = next;
    try {
      if (next) window.localStorage.setItem(TOKEN_KEY, JSON.stringify(next));
      else window.localStorage.removeItem(TOKEN_KEY);
    } catch {
      // Private-mode storage failures should not break the session.
    }
    emit();
  },
  subscribe(listener: (next: TokenPair | null) => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

let refreshInFlight: Promise<TokenPair | null> | null = null;

async function refreshTokens(): Promise<TokenPair | null> {
  const current = tokens;
  if (!current?.refresh_token) return null;
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${API_ROOT}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: current.refresh_token }),
      });
      if (!response.ok) {
        authStore.set(null);
        return null;
      }
      const next = (await response.json()) as TokenPair;
      authStore.set(next);
      return next;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

async function parseError(response: Response): Promise<ApiError> {
  let message = `Request failed (${response.status}).`;
  let code = "request_failed";
  let details: Record<string, unknown> | undefined;
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string; details?: Record<string, unknown> };
      detail?: unknown;
    };
    if (body.error?.message) {
      message = body.error.message;
      code = body.error.code ?? code;
      details = body.error.details;
    } else if (typeof body.detail === "string") {
      message = body.detail;
    } else if (Array.isArray(body.detail) && body.detail.length > 0) {
      const first = body.detail[0] as { msg?: string };
      if (first?.msg) message = first.msg;
      code = "validation_error";
    }
  } catch {
    // Keep the status-based fallback.
  }
  return new ApiError(response.status, message, code, details);
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  auth?: boolean;
  retryOnAuthFailure?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, auth = true, retryOnAuthFailure = true, headers, ...rest } = options;
  const requestHeaders = new Headers(headers);
  if (body !== undefined) requestHeaders.set("Content-Type", "application/json");
  if (auth && tokens?.access_token) {
    requestHeaders.set("Authorization", `Bearer ${tokens.access_token}`);
  }

  const response = await fetch(`${API_ROOT}${path}`, {
    ...rest,
    headers: requestHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401 && auth && retryOnAuthFailure) {
    const next = await refreshTokens();
    if (next) {
      return request<T>(path, { ...options, retryOnAuthFailure: false });
    }
  }

  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function fetchMedia(mediaId: string): Promise<Blob> {
  const attempt = async (retry: boolean): Promise<Response> => {
    const headers = new Headers();
    if (tokens?.access_token) headers.set("Authorization", `Bearer ${tokens.access_token}`);
    const response = await fetch(`${API_ROOT}/media/${mediaId}`, { headers });
    if (response.status === 401 && retry) {
      const next = await refreshTokens();
      if (next) return attempt(false);
    }
    return response;
  };
  const response = await attempt(true);
  if (!response.ok) throw await parseError(response);
  return response.blob();
}

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export interface ComplaintFilters {
  page?: number;
  page_size?: number;
  status?: ComplaintStatus | null;
  category?: ComplaintCategory | null;
  ward?: number | null;
  mine?: boolean;
  q?: string | null;
  sort?: SortKey;
}

export const api = {
  async login(email: string, password: string): Promise<TokenPair> {
    const body = new URLSearchParams({ username: email, password });
    const response = await fetch(`${API_ROOT}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!response.ok) throw await parseError(response);
    const pair = (await response.json()) as TokenPair;
    authStore.set(pair);
    return pair;
  },

  async logout(): Promise<void> {
    const current = tokens;
    authStore.set(null);
    if (!current?.refresh_token) return;
    try {
      await fetch(`${API_ROOT}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: current.refresh_token }),
      });
    } catch {
      // Local logout already happened.
    }
  },

  me(): Promise<MeResponse> {
    return request<MeResponse>("/auth/me");
  },

  /** Perspectives a visitor can open without credentials. */
  demoPerspectives(): Promise<DemoDirectory> {
    return request<DemoDirectory>("/auth/demo", { auth: false });
  },

  /** Open a demo session; the token pair is stored for subsequent calls. */
  async openDemoSession(perspective: string): Promise<TokenPair> {
    const pair = await request<TokenPair>("/auth/demo-session", {
      method: "POST",
      body: { perspective },
      auth: false,
    });
    authStore.set(pair);
    return pair;
  },

  overview(periodDays = 30): Promise<Overview> {
    return request<Overview>(`/analytics/overview${query({ period_days: periodDays })}`);
  },

  mapPoints(params: {
    category?: ComplaintCategory | null;
    status?: ComplaintStatus | null;
    ward?: number | null;
    limit?: number;
  }): Promise<ComplaintMapResponse> {
    return request<ComplaintMapResponse>(`/analytics/map${query(params)}`);
  },

  wards(): Promise<Ward[]> {
    return request<Ward[]>("/wards");
  },

  complaints(filters: ComplaintFilters): Promise<Page<Complaint>> {
    return request<Page<Complaint>>(`/complaints${query({ ...filters })}`);
  },

  complaint(id: string): Promise<Complaint> {
    return request<Complaint>(`/complaints/${id}`);
  },

  audit(id: string): Promise<AuditPage> {
    return request<AuditPage>(`/complaints/${id}/audit`);
  },

  notes(id: string): Promise<InternalNoteList> {
    return request<InternalNoteList>(`/complaints/${id}/notes`);
  },

  addNote(id: string, note: string): Promise<InternalNote> {
    return request<InternalNote>(`/complaints/${id}/notes`, { method: "POST", body: { note } });
  },

  assign(id: string, officerId: string): Promise<Complaint> {
    return request<Complaint>(`/complaints/${id}/assign`, {
      method: "POST",
      body: { officer_id: officerId },
    });
  },

  updateStatus(id: string, status: ComplaintStatus, note?: string): Promise<Complaint> {
    return request<Complaint>(`/complaints/${id}/status`, {
      method: "PATCH",
      body: { status, note: note || null },
    });
  },

  bulkAssign(ids: string[], officerId: string): Promise<BulkResult> {
    return request<BulkResult>("/complaints/bulk/assign", {
      method: "POST",
      body: { complaint_ids: ids, officer_id: officerId },
    });
  },

  bulkStatus(ids: string[], status: ComplaintStatus, note?: string): Promise<BulkResult> {
    return request<BulkResult>("/complaints/bulk/status", {
      method: "POST",
      body: { complaint_ids: ids, status, note: note || null },
    });
  },

  similar(payload: {
    text: string;
    location?: { type: "Point"; coordinates: [number, number] };
    category?: ComplaintCategory;
    limit?: number;
  }): Promise<SimilarIssueResponse> {
    return request<SimilarIssueResponse>("/complaints/similar", {
      method: "POST",
      body: { ...payload, radius_km: 1.5 },
    });
  },

  officers(ward?: number): Promise<Officer[]> {
    return request<Officer[]>(`/users/officers${query({ ward })}`);
  },

  clusters(params: {
    category?: ComplaintCategory | null;
    ward?: number | null;
    min_count?: number;
    limit?: number;
  }): Promise<ClusterResponse> {
    return request<ClusterResponse>(`/clusters/recurring${query(params)}`);
  },

  forecastMap(category: ComplaintCategory, horizonDays = 14): Promise<ForecastMap> {
    return request<ForecastMap>(
      `/forecasts/map${query({ category, horizon_days: horizonDays })}`,
    );
  },

  assistant(question: string): Promise<AssistantResponse> {
    return request<AssistantResponse>("/assistant/query", {
      method: "POST",
      body: { question },
    });
  },

  assistantExamples(): Promise<string[]> {
    return request<string[]>("/assistant/examples");
  },

  recomputeClusters(): Promise<{ clusters: number }> {
    return request<{ clusters: number }>("/clusters/recompute", { method: "POST" });
  },

  publicStats(): Promise<PublicStats> {
    return request<PublicStats>("/public/stats", { auth: false });
  },
};

export function mediaObjectUrl(mediaId: string): Promise<string> {
  return fetchMedia(mediaId).then((blob) => URL.createObjectURL(blob));
}
