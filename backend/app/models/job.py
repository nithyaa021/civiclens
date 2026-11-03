"""Models for asynchronous job endpoints (Celery-backed)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EmbeddingRequest(BaseModel):
    """Request an embedding vector for a piece of text."""

    text: str = Field(
        min_length=1,
        max_length=8000,
        description="Text to embed (complaint title/body, ward note, ...).",
        examples=["Streetlight outside the Sarjapur bus stand has been out for a week."],
    )
    kind: str = Field(
        default="complaint",
        description="Semantic kind of the text; stored alongside the vector.",
        examples=["complaint"],
    )
    source_id: str | None = Field(
        default=None,
        description="Optional id of the document this text belongs to.",
        examples=["665f1c2e9b0d4a2f18c3ab71"],
    )


class NotificationRequest(BaseModel):
    """Queue a notification for delivery to a user."""

    user_id: str = Field(description="Recipient user id.", examples=["665f1c2e9b0d4a2f18c3ab71"])
    subject: str = Field(min_length=1, max_length=200, examples=["Complaint acknowledged"])
    body: str = Field(
        min_length=1,
        max_length=4000,
        examples=["Your pothole report on 14th Main Rd has been assigned to Ward 12."],
    )
    channel: Literal["in_app", "email"] = Field(
        default="in_app",
        description="Delivery channel. 'email' is sent via SMTP when configured, "
        "otherwise stored as an in-app notification and reported as skipped.",
    )


class JobQueued(BaseModel):
    """Acknowledgement that a task was enqueued."""

    task_id: str = Field(
        description="Celery task id; poll GET /jobs/{task_id}.", examples=["8f2b1c4e-..."]
    )
    status: str = Field(default="queued", examples=["queued"])
    queue: str = Field(default="civiclens", examples=["civiclens"])


class JobStatusResponse(BaseModel):
    """Current state of an asynchronous job."""

    task_id: str
    state: Literal["PENDING", "STARTED", "PROGRESS", "SUCCESS", "FAILURE", "RETRY", "REVOKED"]
    result: dict[str, Any] | None = Field(
        default=None, description="Task result payload when state is SUCCESS."
    )
    error: str | None = Field(default=None, description="Failure reason when state is FAILURE.")
    created_at: datetime | None = Field(
        default=None, description="Enqueue time (UTC) recorded by the API."
    )
