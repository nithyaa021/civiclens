"""Dashboard analytics and public transparency payloads.

These models sit on top of the complaint domain: every value is aggregated
from real stored reports.  The public variants deliberately omit reporter,
officer and exact-location data.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.complaint import ComplaintCategory, ComplaintStatus
from app.models.ward import GeoPoint


class KpiSummary(BaseModel):
    """Headline counts for the authority overview."""

    open: int = Field(ge=0)
    resolved_this_week: int = Field(ge=0)
    avg_resolution_days: float | None = Field(description="Mean days to resolution in the period.")
    sla_breaches: int = Field(ge=0, description="Open complaints whose SLA clock has expired.")
    total: int = Field(ge=0)
    resolved_rate: float = Field(ge=0.0, le=1.0)


class TrendPoint(BaseModel):
    """One day of received vs. resolved volume."""

    date: date
    received: int = Field(ge=0)
    resolved: int = Field(ge=0)


class CategoryStat(BaseModel):
    """Volume and resolution mix for one category."""

    category: ComplaintCategory
    count: int = Field(ge=0)
    open: int = Field(ge=0)
    resolved: int = Field(ge=0)
    share: float = Field(ge=0.0, le=1.0)


class OverviewResponse(BaseModel):
    """Authority dashboard overview, scoped to the caller's role."""

    generated_at: datetime
    period_days: int
    scope: Literal["all", "ward"]
    ward: int | None
    kpis: KpiSummary
    trend: list[TrendPoint]
    categories: list[CategoryStat]


class MapComplaint(BaseModel):
    """Lightweight complaint point for the map view."""

    id: str
    title: str
    category: ComplaintCategory
    status: ComplaintStatus
    severity: int
    ward: int | None
    priority: float | None
    location: GeoPoint
    created_at: datetime
    due_at: datetime | None


class ComplaintMapResponse(BaseModel):
    """Map points with a truncation flag for dense cities."""

    items: list[MapComplaint]
    total: int
    truncated: bool
    scope: Literal["all", "ward"]
    ward: int | None


class WardForecastSummary(BaseModel):
    """14-day forecast total for one ward (map overlay)."""

    ward: int
    total_predicted: int = Field(ge=0)
    peak_day: date | None
    peak_predicted: int = Field(ge=0)


class ForecastMapResponse(BaseModel):
    """Per-ward forecast totals for one category."""

    category: ComplaintCategory
    horizon_days: int
    items: list[WardForecastSummary]
    generated_at: datetime


class PublicWardStat(BaseModel):
    """Anonymised ward-level transparency statistics."""

    ward: int
    name: str
    zone: str
    total: int = Field(ge=0)
    open: int = Field(ge=0)
    resolved: int = Field(ge=0)
    avg_resolution_days: float | None
    sla_compliance: float = Field(ge=0.0, le=1.0)
    resolved_rate: float = Field(ge=0.0, le=1.0)


class PublicCategoryStat(BaseModel):
    """Anonymised category mix for the transparency page."""

    category: ComplaintCategory
    total: int = Field(ge=0)
    resolved: int = Field(ge=0)
    share: float = Field(ge=0.0, le=1.0)


class PublicResolution(BaseModel):
    """A recently completed work item, without reporter or officer details."""

    title: str
    category: ComplaintCategory
    ward: int | None
    ward_name: str | None
    resolved_at: datetime
    resolution_days: float | None
    verified: bool


class PublicStats(BaseModel):
    """Everything the public transparency portal needs in one call."""

    generated_at: datetime
    period_days: int
    generated_for: str = "CivicLens municipal transparency portal"
    totals: KpiSummary
    resolved_in_period: int = Field(ge=0)
    wards: list[PublicWardStat]
    categories: list[PublicCategoryStat]
    recent_resolutions: list[PublicResolution]
