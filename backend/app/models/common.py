"""Shared response envelopes and health models."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Standard pagination envelope for list endpoints."""

    items: list[T]
    total: int = Field(description="Total documents matching the query.")
    page: int = Field(ge=1, description="1-based page number.")
    page_size: int = Field(ge=1, description="Items per page.")


class ErrorBody(BaseModel):
    """Machine-readable error detail."""

    code: str = Field(description="Stable error identifier.", examples=["not_found"])
    message: str = Field(
        description="Human-readable explanation.", examples=["User 'x' not found."]
    )
    details: dict = Field(
        default_factory=dict,
        description="Optional structured context (field errors, limits, ...).",
    )


class ErrorResponse(BaseModel):
    """Standard error envelope returned by every non-2xx response."""

    error: ErrorBody


class DependencyStatus(BaseModel):
    """Health of one backing dependency."""

    status: str = Field(description="'ok' or 'error'.", examples=["ok"])
    latency_ms: float = Field(description="Round-trip time of the health probe.", examples=[1.42])
    detail: str | None = Field(default=None, description="Error detail when status is 'error'.")


class HealthResponse(BaseModel):
    """Service health payload."""

    status: str = Field(
        description="'ok' when every critical dependency is reachable.", examples=["ok"]
    )
    service: str = Field(examples=["CivicLens AI"])
    version: str = Field(examples=["0.1.0"])
    environment: str = Field(examples=["development"])
    time: datetime = Field(description="Server time (UTC).")
    dependencies: dict[str, DependencyStatus] = Field(
        description="Per-dependency probe results (mongo, redis).",
        examples=[
            {
                "mongo": {"status": "ok", "latency_ms": 1.42, "detail": None},
                "redis": {"status": "ok", "latency_ms": 0.61, "detail": None},
            }
        ],
    )
