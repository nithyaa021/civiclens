"""Endpoints that enqueue Celery jobs and report their status.

These prove the async pipeline end to end: the API process only enqueues work
onto the broker, the worker executes it, and results are read back through the
Redis result backend.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.core.deps import CurrentUserDep, DbDep, RedisDep, default_rate_limit
from app.core.errors import ApiError, ForbiddenError, NotFoundError
from app.models.job import (
    EmbeddingRequest,
    JobQueued,
    JobStatusResponse,
    NotificationRequest,
)
from app.workers.celery_app import celery_app
from app.workers.tasks.embeddings import generate_embedding
from app.workers.tasks.image_analysis import analyze_image
from app.workers.tasks.notifications import send_notification

router = APIRouter(prefix="/jobs", tags=["jobs"])

OWNER_PREFIX = "job:owner:"
CREATED_PREFIX = "job:created:"
OWNER_TTL_SECONDS = 24 * 3600

# Celery states the API is allowed to surface (anything else reads as PENDING).
_KNOWN_STATES = {"PENDING", "STARTED", "PROGRESS", "SUCCESS", "FAILURE", "RETRY", "REVOKED"}

# Media uploads are capped; larger files are rejected with 413.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp"}


async def _track_owner(redis, task_id: str, user_id: str) -> None:
    """Record who queued a job (ownership check on read) and when."""
    now = datetime.now(UTC)
    await redis.set(f"{OWNER_PREFIX}{task_id}", user_id, ex=OWNER_TTL_SECONDS)
    await redis.set(f"{CREATED_PREFIX}{task_id}", now.isoformat(), ex=OWNER_TTL_SECONDS)


@router.post(
    "/embeddings",
    response_model=JobQueued,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue text embedding generation",
    description=(
        "Enqueues `jobs.generate_embedding`, which computes a deterministic "
        "feature-hashed vector for the text and persists it to the `embeddings` "
        "collection. Poll `GET /jobs/{task_id}` for the outcome."
    ),
    responses={
        202: {"description": "Task accepted for asynchronous processing."},
        401: {"description": "Not authenticated."},
        429: {"description": "Rate limit exceeded."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def queue_embedding(
    payload: EmbeddingRequest,
    user: CurrentUserDep,
    redis: RedisDep,
) -> JobQueued:
    async_result = generate_embedding.delay(
        text=payload.text,
        kind=payload.kind,
        source_id=payload.source_id,
        requested_by=user.id,
    )
    await _track_owner(redis, async_result.id, user.id)
    return JobQueued(task_id=async_result.id)


@router.post(
    "/image-analysis",
    response_model=JobQueued,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue image analysis",
    description=(
        "Uploads an image (multipart form) to the `media` collection and queues "
        "`jobs.analyze_image`. The worker computes real image statistics: "
        "dimensions, format, EXIF presence, mean brightness, a Laplacian "
        "variance blur score and dominant colours. Files above 8 MB or of an "
        "unsupported type are rejected."
    ),
    responses={
        202: {"description": "Task accepted for asynchronous processing."},
        401: {"description": "Not authenticated."},
        413: {"description": "Image exceeds the 8 MB limit."},
        415: {"description": "Unsupported media type."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def queue_image_analysis(
    user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
    file: Annotated[UploadFile, File(description="JPEG, PNG, WebP, TIFF or BMP image.")],
) -> JobQueued:
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ApiError(
            415,
            "unsupported_media_type",
            f"Unsupported image type {content_type or 'unknown'!r}. "
            f"Allowed: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}.",
        )

    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise ApiError(
            413,
            "payload_too_large",
            f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit.",
            details={"size_bytes": len(data), "max_bytes": MAX_IMAGE_BYTES},
        )
    if not data:
        raise ApiError(400, "empty_file", "Uploaded file is empty.")

    media = await db["media"].insert_one(
        {
            "filename": file.filename or "upload",
            "content_type": content_type,
            "size_bytes": len(data),
            "data": data,
            "owner_id": user.id,
            "created_at": datetime.now(UTC),
        }
    )
    async_result = analyze_image.delay(media_id=str(media.inserted_id), requested_by=user.id)
    await _track_owner(redis, async_result.id, user.id)
    return JobQueued(task_id=async_result.id)


@router.post(
    "/notifications",
    response_model=JobQueued,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a notification",
    description=(
        "Enqueues `jobs.send_notification`. The worker resolves the recipient, "
        "persists the notification, and sends an email when SMTP is configured "
        "(otherwise the email is honestly reported as skipped)."
    ),
    responses={
        202: {"description": "Task accepted for asynchronous processing."},
        401: {"description": "Not authenticated."},
        429: {"description": "Rate limit exceeded."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def queue_notification(
    payload: NotificationRequest,
    user: CurrentUserDep,
    redis: RedisDep,
) -> JobQueued:
    async_result = send_notification.delay(
        user_id=payload.user_id,
        subject=payload.subject,
        body=payload.body,
        channel=payload.channel,
        requested_by=user.id,
    )
    await _track_owner(redis, async_result.id, user.id)
    return JobQueued(task_id=async_result.id)


@router.get(
    "/notifications",
    summary="List your notifications",
    description="Most recent in-app notifications delivered to the calling user.",
    responses={
        200: {"description": "Notifications, newest first."},
        401: {"description": "Not authenticated."},
        429: {"description": "Rate limit exceeded."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def list_notifications(user: CurrentUserDep, db: DbDep) -> dict:
    cursor = db["notifications"].find({"user_id": user.id}).sort("created_at", -1).limit(50)
    items = [
        {
            "id": str(doc["_id"]),
            "subject": doc["subject"],
            "body": doc["body"],
            "channel": doc["channel"],
            "created_at": doc["created_at"].isoformat(),
        }
        async for doc in cursor
    ]
    return {"items": items, "count": len(items)}


@router.get(
    "/{task_id}",
    response_model=JobStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll a queued job",
    description=(
        "Returns the Celery state of the task; on `SUCCESS` the task result is "
        "included. Only the user who queued the task may read it."
    ),
    responses={
        200: {"description": "Current task state."},
        401: {"description": "Not authenticated."},
        403: {"description": "Task was queued by a different user."},
        404: {"description": "Unknown or expired task id."},
    },
)
async def job_status(
    task_id: str,
    user: CurrentUserDep,
    redis: RedisDep,
) -> JobStatusResponse:
    owner = await redis.get(f"{OWNER_PREFIX}{task_id}")
    if owner is None:
        raise NotFoundError("Job", task_id)
    if owner != user.id and user.role.value != "admin":
        raise ForbiddenError("This job was queued by another user.")

    async_result = celery_app.AsyncResult(task_id)
    # Read the backend exactly ONCE: reading state/result through separate
    # calls can straddle a worker completion and report SUCCESS with no result.
    meta = async_result.backend.get_task_meta(async_result.id)
    raw_state = str(meta.get("status", "PENDING"))
    state = raw_state if raw_state in _KNOWN_STATES else "PENDING"

    result_payload: dict | None = None
    error: str | None = None
    if state == "SUCCESS":
        raw = meta.get("result")
        result_payload = raw if isinstance(raw, dict) else {"value": raw}
    elif state == "FAILURE":
        error = str(meta.get("result"))

    created_at = await redis.get(f"{CREATED_PREFIX}{task_id}")
    return JobStatusResponse(
        task_id=task_id,
        state=state,
        result=result_payload,
        error=error,
        created_at=datetime.fromisoformat(created_at) if created_at else None,
    )
