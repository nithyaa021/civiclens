"""Complaint domain models: categories, workflow, scoring, and API payloads."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.ward import GeoPoint

TITLE_MIN, TITLE_MAX = 5, 160
DESCRIPTION_MIN, DESCRIPTION_MAX = 10, 4000
MAX_ATTACHMENTS_PER_COMPLAINT = 10


class ComplaintCategory(StrEnum):
    """Municipal complaint taxonomy used for SLA targets and reporting."""

    ROADS = "roads"
    DRAINAGE = "drainage"
    WATER_SUPPLY = "water_supply"
    SANITATION = "sanitation"
    WASTE_MANAGEMENT = "waste_management"
    STREETLIGHT = "streetlight"
    TRAFFIC_SIGNAL = "traffic_signal"
    NOISE = "noise"
    PARKS_TREES = "parks_trees"
    OTHER = "other"


class ComplaintStatus(StrEnum):
    """Lifecycle of a complaint."""

    SUBMITTED = "submitted"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


# Legal status transitions (enforced by the service layer; the API never
# allows arbitrary jumps such as submitted -> closed).
ALLOWED_TRANSITIONS: dict[ComplaintStatus, frozenset[ComplaintStatus]] = {
    ComplaintStatus.SUBMITTED: frozenset({ComplaintStatus.ASSIGNED}),
    ComplaintStatus.ASSIGNED: frozenset({ComplaintStatus.IN_PROGRESS, ComplaintStatus.SUBMITTED}),
    ComplaintStatus.IN_PROGRESS: frozenset({ComplaintStatus.RESOLVED, ComplaintStatus.ASSIGNED}),
    # resolved -> in_progress is the citizen "dispute" path; resolved -> closed
    # happens when the citizen confirms (or the SLA timer expires).
    ComplaintStatus.RESOLVED: frozenset({ComplaintStatus.CLOSED, ComplaintStatus.IN_PROGRESS}),
    ComplaintStatus.CLOSED: frozenset({ComplaintStatus.SUBMITTED}),  # admin reopen
}


class EnrichmentStatus(StrEnum):
    """State of the async ML enrichment pipeline (language/translation/embedding/classification)."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class MlSuggestion(BaseModel):
    """Category proposed by the trained classifier (citizen's own choice wins)."""

    predicted: ComplaintCategory
    confidence: float = Field(ge=0.0, le=1.0, examples=[0.87])
    top: list[tuple[ComplaintCategory, float]] = Field(
        default_factory=list,
        description="Top candidate categories with probabilities.",
    )
    model_version: str = Field(examples=["logreg-minilm-v1"])


class LanguageInfo(BaseModel):
    """Detected language of the original text (or transcript).

    CivicLens translates to English for ``en``/``hi``/``kn``; any other
    detected code is recorded honestly and left untranslated.
    """

    code: str = Field(
        min_length=2, max_length=12, description="Detected language code.", examples=["hi"]
    )
    name: str = Field(examples=["Hindi"])
    confidence: float = Field(ge=0.0, le=1.0, examples=[0.96])
    method: Literal["script", "lingua", "whisper"] = Field(
        description="Detector that produced the result."
    )


class PriorityComponent(BaseModel):
    """One weighted input to the priority score (shown verbatim in the UI)."""

    raw: float = Field(description="Unnormalised measurement for this component.")
    normalized: float = Field(ge=0.0, le=1.0, description="Value scaled to [0, 1].")
    weight: float = Field(ge=0.0, le=1.0, description="Configured weight for this component.")
    contribution: float = Field(ge=0.0, description="normalized * weight * 100.")


class PriorityScore(BaseModel):
    """Transparent priority score with a full breakdown (0-100)."""

    score: float = Field(ge=0.0, le=100.0, examples=[71.5])
    components: dict[str, PriorityComponent]
    formula: str = Field(
        description="Human-readable formula matching the stored components.",
        examples=["0.30*severity + 0.15*frequency + ... (each term scaled to 0-100)"],
    )
    computed_at: datetime


class SlaState(BaseModel):
    """SLA clock and escalation state for one complaint."""

    target_hours: int = Field(ge=1, examples=[72])
    due_at: datetime
    breached: bool = False
    breach_count: int = Field(default=0, ge=0)
    escalation_level: int = Field(default=0, ge=0, description="0=ward, then ladder rungs.")
    escalation_rung: str | None = Field(
        default=None, description="Current ladder rung ('city', 'command') when escalated."
    )
    escalated_at: datetime | None = None
    last_breach_at: datetime | None = None


class ResolutionVerification(BaseModel):
    """Result of the before/after image comparison for a claimed fix."""

    after_media_id: str
    confidence: float = Field(ge=0.0, le=1.0, examples=[0.83])
    passed: bool = Field(description="confidence >= configured pass threshold")
    features: dict[str, float] = Field(
        description="Model inputs (CLIP similarity, SSIM, defect deltas) for explainability."
    )
    model_version: str = Field(examples=["clip-siamese-logreg-v1"])
    note: str | None = None
    verified_at: datetime


class ResolutionRecord(BaseModel):
    """After-photo, model verification and the citizen's final verdict."""

    after_media_id: str
    officer_id: str | None = None
    note: str | None = None
    verification: ResolutionVerification | None = None
    citizen_decision: Literal["confirmed", "disputed"] | None = None
    decision_note: str | None = None
    decided_at: datetime | None = None
    created_at: datetime


class AttachmentRef(BaseModel):
    """Reference to a stored media document."""

    id: str
    kind: Literal["before", "after", "general"] = Field(default="general")
    content_type: str = Field(examples=["image/jpeg"])
    created_at: datetime


class ComplaintBase(BaseModel):
    """Fields shared by create and response payloads."""

    title: str = Field(
        min_length=TITLE_MIN, max_length=TITLE_MAX, examples=["Deep pothole near bus stop"]
    )
    description: str = Field(
        min_length=DESCRIPTION_MIN,
        max_length=DESCRIPTION_MAX,
        examples=["Large pothole opened up after the rain; two-wheelers are falling."],
    )
    category: ComplaintCategory = Field(description="Category chosen by the reporter.")
    severity: int = Field(default=3, ge=1, le=5, description="1 (minor) .. 5 (dangerous).")
    location: GeoPoint = Field(description="Exact location of the issue.")
    address: str = Field(min_length=3, max_length=200, examples=["10th Main, 4th Block, Jayanagar"])
    landmark: str | None = Field(default=None, max_length=200, examples=["Opposite Bus Stop"])


class ComplaintCreate(ComplaintBase):
    """Payload for filing a new complaint."""

    duplicate_of: str | None = Field(
        default=None,
        description=(
            "Set when the reporter saw a similar issue in the pre-submit panel "
            "and chose to support it instead of filing a duplicate."
        ),
    )
    language_code: Literal["en", "hi", "kn"] | None = Field(
        default=None,
        description="Optional hint; language is auto-detected when omitted.",
    )


class ComplaintUpdateStatus(BaseModel):
    """Workflow transition requested by an officer/admin."""

    status: ComplaintStatus
    note: str | None = Field(default=None, max_length=500, description="Stored in the audit trail.")


class PriorityUpdate(BaseModel):
    """Admin-triggered priority recomputation request (no body fields)."""


class ComplaintPublic(ComplaintBase):
    """Full complaint representation returned by the API."""

    id: str = Field(examples=["665f1c2e9b0d4a2f18c3ab71"])
    status: ComplaintStatus
    ward: int | None = Field(default=None, description="Ward derived from the location point.")
    citizen_id: str | None = Field(
        default=None,
        description="Reporter id; hidden unless the caller owns the report or is staff.",
    )
    assigned_officer_id: str | None = None
    votes: int = Field(default=0, ge=0, description="Upvotes from citizens who support the issue.")
    duplicate_of: str | None = None
    language: LanguageInfo | None = None
    english_translation: str | None = Field(
        default=None, description="English translation when the original text is not English."
    )
    category_ml: MlSuggestion | None = None
    enrichment: EnrichmentStatus = EnrichmentStatus.PENDING
    priority: PriorityScore | None = None
    sla: SlaState | None = None
    resolution: ResolutionRecord | None = None
    cluster_id: str | None = Field(default=None, description="Recurring-issue cluster membership.")
    attachments: list[AttachmentRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ComplaintSummary(BaseModel):
    """Compact complaint card used inside similarity/cluster/assistant responses."""

    id: str
    title: str
    category: ComplaintCategory
    status: ComplaintStatus
    severity: int
    ward: int | None
    votes: int
    location: GeoPoint
    address: str
    created_at: datetime


class SimilarIssueQuery(BaseModel):
    """Pre-submit similarity lookup: text (+ optional location) -> nearby duplicates."""

    text: str = Field(
        min_length=5, max_length=1000, examples=["Water logging on 10th main road after rain"]
    )
    location: GeoPoint | None = Field(
        default=None, description="Reporter's location; enables the geo radius filter."
    )
    radius_km: float | None = Field(
        default=None, gt=0, le=50, description="Defaults to server setting."
    )
    category: ComplaintCategory | None = Field(
        default=None, description="Restrict to one category."
    )
    limit: int | None = Field(default=None, ge=1, le=50)


class SimilarIssue(BaseModel):
    """One candidate duplicate with its match score."""

    complaint: ComplaintSummary
    score: float = Field(ge=-1.0, le=1.0, description="Cosine similarity between embeddings.")
    distance_km: float | None = Field(
        default=None, description="Geo distance when a location was given."
    )


class SimilarIssueResponse(BaseModel):
    """Result of the pre-submit similarity check."""

    items: list[SimilarIssue]
    query_language: LanguageInfo | None = None
    min_score: float = Field(description="Threshold applied to the search.")


class ClusterAffectedArea(BaseModel):
    """Area covered by a recurring-issue cluster."""

    centroid: GeoPoint
    radius_km: float = Field(ge=0.0, description="Max distance from centroid to a member.")
    bbox: tuple[tuple[float, float], tuple[float, float]] = Field(
        description="[[min_lng, min_lat], [max_lng, max_lat]]"
    )


class RecurringCluster(BaseModel):
    """A 'recurring issue': geographically tight + semantically similar reports."""

    id: str = Field(examples=["roads:W12:2026-11-01T00:00:00"])
    category: ComplaintCategory
    count: int = Field(ge=1)
    open_count: int = Field(ge=0, description="Members not yet closed.")
    first_reported: datetime
    last_reported: datetime
    affected_area: ClusterAffectedArea
    dominant_ward: int | None = None
    complaint_ids: list[str] = Field(description="Member complaint ids (citations for the UI).")
    computed_at: datetime


class ClusterResponse(BaseModel):
    """Recurring-issue listing for the dashboard."""

    items: list[RecurringCluster]
    lookback_days: int
    computed_at: datetime


class AuditEvent(BaseModel):
    """One immutable audit-trail entry."""

    id: str
    action: str = Field(examples=["status_changed"])
    complaint_id: str | None = None
    actor_id: str | None = None
    actor_role: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    at: datetime


class AuditPage(BaseModel):
    items: list[AuditEvent]
    total: int


class ResolutionDecision(BaseModel):
    """Citizen verdict on a verified fix."""

    note: str | None = Field(default=None, max_length=500)


class ForecastPoint(BaseModel):
    """One predicted daily complaint volume."""

    date: datetime = Field(description="Day the prediction covers (00:00 UTC).")
    predicted: int = Field(ge=0, examples=[7])


class ForecastResponse(BaseModel):
    """14-day hotspot forecast for one ward + category."""

    ward: int
    category: ComplaintCategory
    horizon_days: int
    points: list[ForecastPoint]
    model: str = Field(examples=["xgboost-v1"])
    trained_at: datetime | None = Field(
        default=None, description="When the model artifact was fitted."
    )
    holdout_mae: float | None = Field(
        default=None, description="MAE on the held-out tail of history."
    )
    generated_at: datetime


class AssistantQuery(BaseModel):
    """Natural-language question over complaint data."""

    question: str = Field(
        min_length=5,
        max_length=500,
        examples=["Top recurring issues in Ward 12 this month"],
    )


class AssistantCitation(BaseModel):
    """A complaint id the answer is grounded in."""

    complaint_id: str
    title: str
    status: ComplaintStatus
    category: ComplaintCategory


class AssistantResponse(BaseModel):
    """Grounded answer with citations and the visibility scope that was applied."""

    answer: str
    intent: str = Field(examples=["top_recurring"])
    scope: str = Field(description="Visibility filter applied: 'own', 'ward', or 'all'.")
    citations: list[AssistantCitation]
    clarification: str | None = Field(
        default=None, description="Set when the question was ambiguous."
    )
