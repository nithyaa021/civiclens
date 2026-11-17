import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  CircleDot,
  ClipboardCheck,
  ExternalLink,
  Image as ImageIcon,
  MapPin,
  MessageSquare,
  ShieldAlert,
  UserRound,
} from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useTheme } from "../lib/themeContext";
import { usePageTitle } from "../lib/usePageTitle";
import { categoryMeta, severityLabel, statusActionLabel, statusTransitions } from "../lib/meta";
import {
  ageDays,
  formatDate,
  formatDateTime,
  formatDays,
  formatNumber,
  relativeTime,
  shortId,
  titleCase,
} from "../lib/format";
import { CategoryLabel, SeverityBadge, SlaChip, StatusBadge, Tag } from "../components/Badges";
import { CivicMap } from "../components/CivicMap";
import { Dialog } from "../components/Dialog";
import { AuthImage, PhotoGallery } from "../components/Evidence";
import { PriorityBreakdown } from "../components/PriorityBreakdown";
import { EmptyState, ErrorState, Spinner } from "../components/States";
import { Skeleton, SkeletonLines } from "../components/Skeleton";
import type {
  AuditEvent,
  Complaint,
  ComplaintStatus,
  InternalNote,
  SimilarIssue,
} from "../lib/types";

const ACTION_LABEL: Record<string, string> = {
  created: "Complaint filed",
  status_changed: "Status changed",
  assigned: "Officer assigned",
  note_added: "Internal note added",
  resolution_submitted: "Resolution evidence submitted",
  resolution_confirmed: "Citizen confirmed resolution",
  resolution_disputed: "Citizen disputed resolution",
  sla_breached: "SLA escalation",
  priority_recomputed: "Priority recomputed",
  enriched: "Enrichment completed",
  media_uploaded: "Photo uploaded",
  voted: "Citizen support added",
};

function actorLabel(role: string | null): string {
  if (role === "admin") return "City administrator";
  if (role === "ward_officer") return "Ward officer";
  if (role === "citizen") return "Citizen";
  return "System";
}

function detailText(event: AuditEvent): string | null {
  const details = event.details ?? {};
  if (event.action === "status_changed") {
    const from = typeof details.from === "string" ? titleCase(details.from) : null;
    const to = typeof details.to === "string" ? titleCase(details.to) : null;
    const note = typeof details.note === "string" && details.note ? ` — ${details.note}` : "";
    if (from && to) return `${from} → ${to}${note}`;
  }
  if (typeof details.note === "string" && details.note) return details.note;
  if (typeof details.reason === "string") return titleCase(details.reason);
  return null;
}

function ActionIcon({ action }: { action: string }) {
  if (action === "status_changed") return <CircleDot className="h-3 w-3" aria-hidden />;
  if (action === "assigned") return <UserRound className="h-3 w-3" aria-hidden />;
  if (action === "note_added") return <MessageSquare className="h-3 w-3" aria-hidden />;
  if (action.startsWith("resolution_")) return <ClipboardCheck className="h-3 w-3" aria-hidden />;
  if (action === "sla_breached") return <ShieldAlert className="h-3 w-3" aria-hidden />;
  return <CheckCircle2 className="h-3 w-3" aria-hidden />;
}

function Timeline({ events }: { events: AuditEvent[] }) {
  return (
    <ol className="relative max-h-[430px] space-y-0 overflow-y-auto pr-1">
      {events.map((event, index) => {
        const detail = detailText(event);
        return (
          <li key={event.id} className="relative flex gap-3 pb-4 last:pb-0">
            <div className="relative flex flex-col items-center">
              <span className="z-[1] flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line bg-surface text-muted">
                <ActionIcon action={event.action} />
              </span>
              {index < events.length - 1 ? (
                <span className="absolute top-6 h-full w-px bg-line" aria-hidden />
              ) : null}
            </div>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                <p className="text-[12px] font-medium text-ink">
                  {ACTION_LABEL[event.action] ?? titleCase(event.action)}
                </p>
                <time
                  className="text-[10px] text-faint"
                  dateTime={event.at}
                  title={formatDateTime(event.at)}
                >
                  {relativeTime(event.at)}
                </time>
              </div>
              {detail ? <p className="mt-0.5 text-[11px] leading-4 text-muted">{detail}</p> : null}
              <p className="mt-0.5 text-[10px] text-faint">{actorLabel(event.actor_role)}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function SimilarList({ items }: { items: SimilarIssue[] }) {
  return (
    <ul className="divide-y divide-line">
      {items.map((item) => (
        <li key={item.complaint.id}>
          <Link
            to={`/queue/${item.complaint.id}`}
            className="flex items-start gap-2.5 px-3 py-2.5 hover:bg-raised"
          >
            <span className="tabular mt-0.5 shrink-0 rounded border border-line bg-raised px-1.5 py-0.5 text-[10px] font-medium text-muted">
              {(item.score * 100).toFixed(0)}%
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[12px] font-medium text-ink">
                {item.complaint.title}
              </span>
              <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px] text-muted">
                <CategoryLabel category={item.complaint.category} showIcon={false} className="text-[10px]" />
                <span>Ward {item.complaint.ward ?? "—"}</span>
                <span>{relativeTime(item.complaint.created_at)}</span>
                {item.distance_km !== null ? <span>{item.distance_km.toFixed(1)} km away</span> : null}
              </span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function EvidenceBlock({ complaint }: { complaint: Complaint }) {
  const resolution = complaint.resolution;
  const before = complaint.attachments.find((attachment) => attachment.kind === "before");

  if (!resolution) {
    return (
      <p className="text-[11px] leading-5 text-muted">
        Completion evidence is captured when a field crew submits an after-photo. No resolution has
        been recorded for this case.
      </p>
    );
  }

  const verification = resolution.verification;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <figure>
          <div className="aspect-[4/3] overflow-hidden rounded border border-line bg-raised">
            {before ? (
              <AuthImage mediaId={before.id} alt="Before repair" className="h-full w-full" />
            ) : (
              <div className="flex h-full items-center justify-center text-[10px] text-faint">No before photo</div>
            )}
          </div>
          <figcaption className="mt-1 text-[10px] text-faint">Before</figcaption>
        </figure>
        <figure>
          <div className="aspect-[4/3] overflow-hidden rounded border border-line bg-raised">
            <AuthImage mediaId={resolution.after_media_id} alt="After repair" className="h-full w-full" />
          </div>
          <figcaption className="mt-1 text-[10px] text-faint">After</figcaption>
        </figure>
      </div>

      {verification ? (
        <div className="rounded border border-line bg-raised p-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-medium text-ink">Image verification</span>
            <Tag tone={verification.passed ? "positive" : "neutral"}>
              {verification.passed ? "Passed" : "Review required"}
            </Tag>
          </div>
          <dl className="tabular mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
            <dt className="text-faint">Confidence</dt>
            <dd className="text-right text-ink">{(verification.confidence * 100).toFixed(1)}%</dd>
            <dt className="text-faint">Model</dt>
            <dd className="truncate text-right text-ink">{verification.model_version}</dd>
            <dt className="text-faint">Verified</dt>
            <dd className="text-right text-ink">{formatDate(verification.verified_at)}</dd>
          </dl>
          {verification.note ? (
            <p className="mt-1.5 text-[10px] leading-4 text-muted">{verification.note}</p>
          ) : null}
        </div>
      ) : (
        <p className="text-[11px] text-muted">Verification is pending the comparison worker.</p>
      )}

      <dl className="space-y-1 text-[11px]">
        <div className="flex justify-between gap-2">
          <dt className="text-faint">Submitted</dt>
          <dd className="text-ink">{formatDateTime(resolution.created_at)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-faint">Citizen decision</dt>
          <dd className="text-ink">
            {resolution.citizen_decision ? titleCase(resolution.citizen_decision) : "Pending"}
          </dd>
        </div>
        {resolution.note ? (
          <div>
            <dt className="text-faint">Crew note</dt>
            <dd className="mt-0.5 text-muted">{resolution.note}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

export function ComplaintDetailPage() {
  const { id = "" } = useParams();
  const { theme } = useTheme();
  const { user } = useAuth();
  const isStaff = user?.role === "admin" || user?.role === "ward_officer";
  const queryClient = useQueryClient();
  const [pendingStatus, setPendingStatus] = useState<ComplaintStatus | null>(null);
  const [statusNote, setStatusNote] = useState("");
  const [officerId, setOfficerId] = useState("");
  const [noteDraft, setNoteDraft] = useState("");

  const complaintQuery = useQuery({
    queryKey: ["complaint", id],
    queryFn: () => api.complaint(id),
    enabled: Boolean(id),
  });
  const complaint = complaintQuery.data;
  usePageTitle(complaint ? `${shortId(complaint.id)} · ${complaint.title}` : "Complaint detail");

  const audit = useQuery({
    queryKey: ["audit", id],
    queryFn: () => api.audit(id),
    enabled: Boolean(id),
  });
  const notes = useQuery({
    queryKey: ["notes", id],
    queryFn: () => api.notes(id),
    enabled: Boolean(id) && isStaff,
  });
  const officers = useQuery({
    queryKey: ["officers"],
    queryFn: () => api.officers(),
    staleTime: 120_000,
    enabled: isStaff,
  });
  const wards = useQuery({ queryKey: ["wards"], queryFn: api.wards, staleTime: 120_000 });

  const similar = useQuery({
    queryKey: ["similar", id],
    queryFn: () =>
      api.similar({
        text: `${complaint?.title ?? ""} ${complaint?.description ?? ""}`.trim(),
        location: complaint?.location,
        category: complaint?.category,
        limit: 5,
      }),
    enabled: Boolean(complaint),
    retry: false,
    staleTime: 300_000,
  });

  useEffect(() => {
    if (complaint) setOfficerId(complaint.assigned_officer_id ?? "");
  }, [complaint]);

  const assign = useMutation({
    mutationFn: () => api.assign(id, officerId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["complaint", id] });
      void queryClient.invalidateQueries({ queryKey: ["audit", id] });
      void queryClient.invalidateQueries({ queryKey: ["complaints"] });
    },
  });

  const transition = useMutation({
    mutationFn: (status: ComplaintStatus) => api.updateStatus(id, status, statusNote || undefined),
    onSuccess: () => {
      setPendingStatus(null);
      setStatusNote("");
      void queryClient.invalidateQueries({ queryKey: ["complaint", id] });
      void queryClient.invalidateQueries({ queryKey: ["audit", id] });
      void queryClient.invalidateQueries({ queryKey: ["complaints"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const addNote = useMutation({
    mutationFn: () => api.addNote(id, noteDraft.trim()),
    onSuccess: () => {
      setNoteDraft("");
      void queryClient.invalidateQueries({ queryKey: ["notes", id] });
      void queryClient.invalidateQueries({ queryKey: ["audit", id] });
    },
  });

  const assignedOfficer = useMemo(
    () => (officers.data ?? []).find((officer) => officer.id === complaint?.assigned_officer_id),
    [officers.data, complaint?.assigned_officer_id],
  );

  const mapPoints = useMemo(() => {
    if (!complaint) return [];
    return [
      {
        id: complaint.id,
        title: complaint.title,
        category: complaint.category,
        status: complaint.status,
        severity: complaint.severity,
        ward: complaint.ward,
        priority: complaint.priority?.score ?? null,
        location: complaint.location,
        created_at: complaint.created_at,
        due_at: complaint.sla?.due_at ?? null,
      },
    ];
  }, [complaint]);

  if (complaintQuery.isPending) {
    return (
      <div className="mx-auto max-w-[1440px] space-y-4">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-9 w-2/3" />
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
          <div className="space-y-4">
            <div className="card space-y-3 p-4">
              <SkeletonLines lines={6} />
            </div>
            <div className="card p-4">
              <Skeleton className="h-[240px] w-full" />
            </div>
          </div>
          <div className="space-y-4">
            <div className="card space-y-2 p-4">
              <SkeletonLines lines={4} />
            </div>
            <div className="card space-y-2 p-4">
              <SkeletonLines lines={6} />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (complaintQuery.isError || !complaint) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <Link to="/queue" className="btn btn-ghost btn-sm -ml-2">
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
          Back to queue
        </Link>
        <ErrorState
          error={complaintQuery.error}
          onRetry={() => void complaintQuery.refetch()}
          title="Complaint unavailable"
        />
      </div>
    );
  }

  const category = categoryMeta[complaint.category];
  const CategoryIcon = category.icon;
  const language = complaint.language;
  const ml = complaint.category_ml;
  const transitions = statusTransitions[complaint.status];
  const actionsDisabled = false;

  return (
    <div className="mx-auto max-w-[1440px] space-y-4">
      <div>
        <Link to="/queue" className="btn btn-ghost btn-sm -ml-2 mb-1">
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
          {isStaff ? "Complaint queue" : "My complaints"}
        </Link>
        <div className="flex flex-col gap-3 border-b border-line pb-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <span className="tabular text-[11px] font-medium text-faint">
                #{shortId(complaint.id)}
              </span>
              <StatusBadge status={complaint.status} />
              <SeverityBadge severity={complaint.severity} />
              <Tag>{severityLabel[complaint.severity] ?? "Unrated"}</Tag>
            </div>
            <h1 className="text-[21px] font-semibold leading-tight tracking-[-0.015em] text-ink">
              {complaint.title}
            </h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted">
              <span className="inline-flex items-center gap-1.5">
                <CategoryIcon className={`h-3.5 w-3.5 ${category.className}`} aria-hidden />
                {category.label}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <MapPin className="h-3.5 w-3.5 text-faint" aria-hidden />
                {complaint.address}
              </span>
              <span className="tabular">Ward {complaint.ward ?? "—"}</span>
              <span>Reported {formatDateTime(complaint.created_at)}</span>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <SlaChip sla={complaint.sla} status={complaint.status} />
            <Link
              to={`/map?category=${complaint.category}&ward=${complaint.ward ?? ""}`}
              className="btn btn-secondary btn-sm"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              View on map
            </Link>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <div className="space-y-4">
          <section className="card p-4" aria-labelledby="summary-heading">
            <div className="flex items-start justify-between gap-3">
              <h2 id="summary-heading" className="section-title">
                Report summary
              </h2>
              <div className="flex flex-wrap items-center justify-end gap-1.5">
                {complaint.votes > 0 ? <Tag tone="info">{formatNumber(complaint.votes)} supports</Tag> : null}
                {language ? (
                  <Tag>
                    {language.name}
                    {language.confidence ? ` · ${(language.confidence * 100).toFixed(0)}%` : ""}
                  </Tag>
                ) : null}
              </div>
            </div>
            <p className="mt-2.5 whitespace-pre-line text-[13px] leading-6 text-ink">
              {complaint.description}
            </p>

            {complaint.english_translation ? (
              <div className="mt-3 rounded border border-line bg-raised p-3">
                <p className="eyebrow mb-1">English translation</p>
                <p className="whitespace-pre-line text-[12px] leading-5 text-muted">
                  {complaint.english_translation}
                </p>
              </div>
            ) : null}

            <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-2 border-t border-line pt-3 text-[12px] sm:grid-cols-2">
              <div>
                <dt className="text-faint">Landmark</dt>
                <dd className="mt-0.5 text-ink">{complaint.landmark ?? "Not provided"}</dd>
              </div>
              <div>
                <dt className="text-faint">Ward</dt>
                <dd className="mt-0.5 text-ink">
                  {wards.data?.find((ward) => ward.ward_no === complaint.ward)?.name ?? `Ward ${complaint.ward ?? "—"}`}
                </dd>
              </div>
              <div>
                <dt className="text-faint">Last updated</dt>
                <dd className="mt-0.5 text-ink">{formatDateTime(complaint.updated_at)}</dd>
              </div>
              <div>
                <dt className="text-faint">Age</dt>
                <dd className="mt-0.5 text-ink">{ageDays(complaint.created_at)} days</dd>
              </div>
              {complaint.duplicate_of ? (
                <div className="sm:col-span-2">
                  <dt className="text-faint">Linked duplicate of</dt>
                  <dd className="mt-0.5">
                    <Link to={`/queue/${complaint.duplicate_of}`} className="link text-[12px]">
                      {shortId(complaint.duplicate_of)}
                    </Link>
                  </dd>
                </div>
              ) : null}
            </dl>

            {ml && ml.predicted !== complaint.category ? (
              <p className="mt-3 rounded border border-[color:var(--info-border)] bg-[color:var(--info-soft)] px-2.5 py-2 text-[11px] text-muted">
                Classifier suggestion: <strong className="text-ink">{titleCase(ml.predicted)}</strong>{" "}
                ({(ml.confidence * 100).toFixed(0)}% confidence). Reported category remains{" "}
                {category.label}.
              </p>
            ) : null}
          </section>

          <section className="card overflow-hidden" aria-labelledby="photos-heading">
            <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
              <h2 id="photos-heading" className="section-title">
                Evidence photos
              </h2>
              <span className="text-[11px] text-faint">{complaint.attachments.length} attached</span>
            </div>
            <div className="p-3">
              <PhotoGallery attachments={complaint.attachments} />
            </div>
          </section>

          <section className="card overflow-hidden" aria-labelledby="location-heading">
            <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
              <h2 id="location-heading" className="section-title">
                Location
              </h2>
              <span className="tabular text-[11px] text-faint">
                {complaint.location.coordinates[1].toFixed(5)}, {complaint.location.coordinates[0].toFixed(5)}
              </span>
            </div>
            <div className="h-[260px]">
              <CivicMap
                complaints={mapPoints}
                wards={wards.data ?? []}
                heat={false}
                forecast={null}
                showForecast={false}
                showWards
                theme={theme}
                center={[complaint.location.coordinates[1], complaint.location.coordinates[0]]}
                zoom={15}
              />
            </div>
          </section>

          <section className="card overflow-hidden" aria-labelledby="similar-heading">
            <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
              <div>
                <h2 id="similar-heading" className="section-title">
                  Similar issues
                </h2>
                <p className="mt-0.5 text-[11px] text-muted">Nearest semantic matches in this category</p>
              </div>
              {similar.data ? (
                <span className="text-[10px] text-faint">
                  min score {(similar.data.min_score * 100).toFixed(0)}%
                </span>
              ) : null}
            </div>
            {similar.isPending ? (
              <div className="space-y-3 p-4">
                <SkeletonLines lines={3} />
              </div>
            ) : similar.isError ? (
              <p className="px-4 py-4 text-[11px] leading-5 text-muted">
                Similarity search is unavailable right now. The vector index may still be warming up.
              </p>
            ) : similar.data.items.length === 0 ? (
              <EmptyState
                title="No similar reports found"
                description="This issue does not currently match other reports above the similarity threshold."
              />
            ) : (
              <SimilarList items={similar.data.items} />
            )}
          </section>

          <section className="card overflow-hidden" aria-labelledby="timeline-heading">
            <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
              <h2 id="timeline-heading" className="section-title">
                Case timeline
              </h2>
              <span className="text-[11px] text-faint">{audit.data?.total ?? 0} events</span>
            </div>
            <div className="p-4">
              {audit.isPending ? (
                <SkeletonLines lines={6} />
              ) : audit.isError ? (
                <ErrorState error={audit.error} onRetry={() => void audit.refetch()} title="Timeline unavailable" />
              ) : audit.data.items.length === 0 ? (
                <p className="text-[12px] text-muted">No audit events have been recorded.</p>
              ) : (
                <Timeline events={audit.data.items} />
              )}
            </div>
          </section>
        </div>

        <div className="space-y-4">
          {isStaff ? (
          <section className="card p-4" aria-labelledby="actions-heading">
            <h2 id="actions-heading" className="section-title">
              Case actions
            </h2>
            <div className="mt-3">
              <label htmlFor="assign-officer" className="label">
                Assigned officer
              </label>
              <div className="flex gap-2">
                <select
                  id="assign-officer"
                  className="field"
                  value={officerId}
                  onChange={(event) => setOfficerId(event.target.value)}
                  disabled={complaint.status === "closed"}
                >
                  <option value="">Unassigned</option>
                  {(officers.data ?? []).map((officer) => (
                    <option key={officer.id} value={officer.id}>
                      {officer.full_name} · Ward {officer.ward ?? "—"}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn-secondary shrink-0"
                  disabled={!officerId || assign.isPending || officerId === complaint.assigned_officer_id}
                  onClick={() => assign.mutate()}
                >
                  {assign.isPending ? <Spinner /> : "Assign"}
                </button>
              </div>
              <p className="mt-1 text-[10px] text-muted">
                {assignedOfficer ? `Currently ${assignedOfficer.full_name}.` : "No officer assigned."}
              </p>
              {assign.isError ? (
                <p className="mt-1 text-[11px] text-[color:var(--critical)]" role="alert">
                  {assign.error instanceof Error ? assign.error.message : "Assignment failed."}
                </p>
              ) : null}
            </div>

            <div className="mt-4 border-t border-line pt-3">
              <p className="label">Workflow transitions</p>
              <div className="flex flex-wrap gap-1.5">
                {transitions.map((status) => (
                  <button
                    key={status}
                    type="button"
                    className={
                      status === "closed"
                        ? "btn btn-secondary btn-sm"
                        : status === "resolved"
                          ? "btn btn-primary btn-sm"
                          : "btn btn-secondary btn-sm"
                    }
                    disabled={actionsDisabled}
                    onClick={() => {
                      setStatusNote("");
                      setPendingStatus(status);
                    }}
                  >
                    {statusActionLabel[status]}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[10px] leading-4 text-muted">
                {complaint.status === "in_progress"
                  ? "Resolution requires a verified after-photo from the field crew."
                  : "Every transition is written to the immutable audit trail and notifies the reporter."}
              </p>
            </div>
          </section>
          ) : null}

          <section className="card p-4" aria-labelledby="sla-heading">
            <h2 id="sla-heading" className="section-title">
              Service level
            </h2>
            <div className="mt-3 space-y-2.5 text-[12px]">
              <div className="flex items-start justify-between gap-2">
                <span className="flex items-center gap-1.5 text-muted">
                  <CalendarClock className="h-3.5 w-3.5 text-faint" aria-hidden />
                  Due
                </span>
                <span className="text-right text-ink">{formatDateTime(complaint.sla?.due_at ?? null)}</span>
              </div>
              <div className="flex items-start justify-between gap-2">
                <span className="text-muted">Target</span>
                <span className="tabular text-ink">
                  {complaint.sla ? `${formatNumber(complaint.sla.target_hours)} hours` : "—"}
                </span>
              </div>
              <div className="flex items-start justify-between gap-2">
                <span className="text-muted">Breach state</span>
                <span>
                  {complaint.sla?.breached ? (
                    <Tag>{`${complaint.sla.breach_count} breach${complaint.sla.breach_count === 1 ? "" : "es"}`}</Tag>
                  ) : (
                    <Tag tone="positive">Within target</Tag>
                  )}
                </span>
              </div>
              <div className="flex items-start justify-between gap-2">
                <span className="text-muted">Escalation</span>
                <span className="text-ink">
                  {complaint.sla?.escalation_level
                    ? `Level ${complaint.sla.escalation_level} · ${complaint.sla.escalation_rung ?? "city"}`
                    : "None"}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 border-t border-line pt-2.5">
                <span className="text-muted">Resolution time</span>
                <span className="tabular text-ink">
                  {complaint.resolution
                    ? formatDays(
                        (new Date(complaint.updated_at).getTime() -
                          new Date(complaint.created_at).getTime()) /
                          86_400_000,
                      )
                    : "Open"}
                </span>
              </div>
            </div>
            {complaint.sla?.breached ? (
              <p className="mt-2.5 flex items-start gap-1.5 rounded border border-[color:var(--critical-border)] bg-[color:var(--critical-soft)] px-2 py-1.5 text-[10px] leading-4 text-[color:var(--critical)]">
                <ShieldAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                SLA clock has expired. Escalation notices have been issued to the ward queue.
              </p>
            ) : null}
          </section>

          <section className="card p-4" aria-labelledby="priority-heading">
            <h2 id="priority-heading" className="section-title mb-3">
              Priority factors
            </h2>
            <PriorityBreakdown priority={complaint.priority} />
          </section>

          <section className="card p-4" aria-labelledby="verification-heading">
            <h2 id="verification-heading" className="section-title mb-3">
              Before / after verification
            </h2>
            <EvidenceBlock complaint={complaint} />
          </section>

          {isStaff ? (
          <section className="card overflow-hidden" aria-labelledby="notes-heading">
            <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
              <div>
                <h2 id="notes-heading" className="section-title">
                  Internal notes
                </h2>
                <p className="mt-0.5 text-[10px] text-faint">Staff only · never shown to reporters</p>
              </div>
              <MessageSquare className="h-3.5 w-3.5 text-faint" aria-hidden />
            </div>
            <div className="max-h-[260px] divide-y divide-line overflow-y-auto">
              {notes.isPending ? (
                <div className="p-4">
                  <SkeletonLines lines={3} />
                </div>
              ) : notes.isError ? (
                <p className="p-4 text-[11px] text-muted">Internal notes are not available for this case.</p>
              ) : notes.data.items.length === 0 ? (
                <p className="px-4 py-4 text-[11px] text-muted">
                  No internal notes yet. Use the field below to record dispatch details.
                </p>
              ) : (
                notes.data.items.map((note: InternalNote) => (
                  <div key={note.id} className="px-4 py-2.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="text-[11px] font-medium text-ink">{note.author_name}</p>
                      <time className="text-[10px] text-faint" dateTime={note.created_at}>
                        {relativeTime(note.created_at)}
                      </time>
                    </div>
                    <p className="mt-1 whitespace-pre-line text-[11px] leading-5 text-muted">{note.note}</p>
                  </div>
                ))
              )}
            </div>
            <form
              className="border-t border-line p-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (noteDraft.trim()) addNote.mutate();
              }}
            >
              <label htmlFor="note-draft" className="label">
                Add a note
              </label>
              <textarea
                id="note-draft"
                className="field-textarea min-h-[70px]"
                maxLength={2000}
                placeholder="Crew ETA, access constraints, contractor reference…"
                value={noteDraft}
                onChange={(event) => setNoteDraft(event.target.value)}
              />
              {addNote.isError ? (
                <p className="mt-1 text-[11px] text-[color:var(--critical)]" role="alert">
                  {addNote.error instanceof Error ? addNote.error.message : "Could not add note."}
                </p>
              ) : null}
              <div className="mt-2 flex justify-end">
                <button
                  type="submit"
                  className="btn btn-secondary btn-sm"
                  disabled={!noteDraft.trim() || addNote.isPending}
                >
                  {addNote.isPending ? <Spinner /> : <MessageSquare className="h-3.5 w-3.5" aria-hidden />}
                  Save note
                </button>
              </div>
            </form>
          </section>
          ) : null}
        </div>
      </div>

      <Dialog
        open={pendingStatus !== null}
        onClose={() => setPendingStatus(null)}
        title={pendingStatus ? statusActionLabel[pendingStatus] : "Update status"}
        description={
          pendingStatus
            ? `Move this case from ${complaint.status.replace("_", " ")} to ${pendingStatus.replace("_", " ")}.`
            : undefined
        }
        footer={
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setPendingStatus(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={transition.isPending}
              onClick={() => {
                if (pendingStatus) transition.mutate(pendingStatus);
              }}
            >
              {transition.isPending ? "Updating…" : "Confirm update"}
            </button>
          </>
        }
      >
        {transition.isError ? (
          <div className="mb-3">
            <ErrorState
              error={transition.error}
              title="Transition rejected"
              onRetry={() => transition.reset()}
            />
          </div>
        ) : null}
        <label htmlFor="transition-note" className="label">
          Note <span className="font-normal text-faint">(optional, written to audit)</span>
        </label>
        <textarea
          id="transition-note"
          className="field-textarea"
          maxLength={500}
          value={statusNote}
          onChange={(event) => setStatusNote(event.target.value)}
          placeholder="Dispatch details for the record"
        />
        {pendingStatus === "resolved" ? (
          <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-5 text-muted">
            <ImageIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-faint" aria-hidden />
            Resolutions require a verified after-photo except when completed by an administrator.
          </p>
        ) : null}
      </Dialog>
    </div>
  );
}
