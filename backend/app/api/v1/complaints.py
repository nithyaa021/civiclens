"""Complaint endpoints: filing, workflow, voting, photos, resolution, similarity."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.core.deps import CurrentUserDep, DbDep, SettingsDep, default_rate_limit
from app.core.errors import ForbiddenError
from app.core.uploads import ALLOWED_IMAGE_TYPES, MAX_IMAGE_BYTES, validate_upload
from app.models.common import Page
from app.models.complaint import (
    AttachmentRef,
    AuditPage,
    ComplaintCreate,
    ComplaintPublic,
    ComplaintStatus,
    ComplaintUpdateStatus,
    ResolutionDecision,
    SimilarIssueQuery,
    SimilarIssueResponse,
)
from app.models.user import Role
from app.services import audit as audit_service
from app.services import complaints as service
from app.workers.tasks.enrich import enrich_complaint
from app.workers.tasks.resolution import verify_resolution

router = APIRouter(prefix="/complaints", tags=["complaints"])


@router.post(
    "",
    response_model=ComplaintPublic,
    status_code=status.HTTP_201_CREATED,
    summary="File a complaint",
    description=(
        "Resolves the ward from the pin, auto-assigns the ward officer when one "
        "exists, starts the per-category SLA clock, computes the initial priority "
        "score, and queues the enrichment pipeline (language detection, English "
        "translation, embedding, category suggestion). Pass `duplicate_of` when the "
        "reporter chose to support an existing issue instead of duplicating it."
    ),
    responses={
        201: {"description": "Complaint created."},
        400: {"description": "Location outside the service area or invalid duplicate id."},
        401: {"description": "Not authenticated."},
        422: {"description": "Validation error."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def create_complaint(
    payload: ComplaintCreate,
    user: CurrentUserDep,
    db: DbDep,
    settings: SettingsDep,
) -> ComplaintPublic:
    created = await service.create_complaint(db, payload, user, settings)
    enrich_complaint.delay(created.id)
    return created


@router.post(
    "/similar",
    response_model=SimilarIssueResponse,
    status_code=status.HTTP_200_OK,
    summary="Find similar issues nearby (before submitting)",
    description=(
        "Embeds the draft text with the multilingual sentence-transformer model and "
        "runs an indexed vector search in Qdrant, optionally constrained by category "
        "and a geo radius around the reporter's pin. Use the returned ids to let the "
        "citizen upvote an existing complaint instead of filing a duplicate."
    ),
    responses={
        200: {"description": "Ranked similar issues (possibly empty)."},
        401: {"description": "Not authenticated."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def find_similar(
    payload: SimilarIssueQuery,
    user: CurrentUserDep,
    db: DbDep,
    settings: SettingsDep,
) -> SimilarIssueResponse:
    return await service.find_similar_issues(db, payload, settings)


@router.get(
    "",
    response_model=Page[ComplaintPublic],
    status_code=status.HTTP_200_OK,
    summary="List complaints",
    description=(
        "Municipal records are readable by every authenticated user; the reporter id "
        "is only exposed to the owner and staff. Use `mine=true` for your own reports."
    ),
    responses={
        200: {"description": "Page of complaints."},
        401: {"description": "Not authenticated."},
    },
)
async def list_complaints(
    user: CurrentUserDep,
    db: DbDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[ComplaintStatus | None, Query(alias="status")] = None,
    category: Annotated[str | None, Query(max_length=40)] = None,
    ward: Annotated[int | None, Query(ge=1, le=999)] = None,
    mine: Annotated[bool, Query(description="Only the caller's own reports.")] = False,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    sort: Annotated[Literal["newest", "oldest", "priority", "due"], Query()] = "newest",
) -> Page[ComplaintPublic]:
    return await service.list_complaints(
        db,
        user,
        page=page,
        page_size=page_size,
        status=status_filter,
        category=category,
        ward=ward,
        mine=mine,
        q=q,
        sort=sort,
    )


@router.get(
    "/{complaint_id}",
    response_model=ComplaintPublic,
    status_code=status.HTTP_200_OK,
    summary="Fetch one complaint",
    responses={
        200: {"description": "Complaint found."},
        401: {"description": "Not authenticated."},
        404: {"description": "Unknown complaint id."},
    },
)
async def get_complaint(complaint_id: str, user: CurrentUserDep, db: DbDep) -> ComplaintPublic:
    return await service.get_complaint(db, complaint_id, user)


@router.get(
    "/{complaint_id}/audit",
    response_model=AuditPage,
    status_code=status.HTTP_200_OK,
    summary="Audit trail for one complaint",
    description=(
        "Full immutable history (creation, assignment, status changes, SLA breaches, "
        "resolution verification and the citizen's verdict). Visible to the reporter "
        "and staff."
    ),
    responses={
        200: {"description": "Audit entries, oldest first."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller cannot see this complaint's history."},
        404: {"description": "Unknown complaint id."},
    },
)
async def get_audit(complaint_id: str, user: CurrentUserDep, db: DbDep) -> AuditPage:
    complaint = await service.get_complaint(db, complaint_id, user)
    if (
        user.role == Role.CITIZEN
        and complaint.citizen_id is not None
        and complaint.citizen_id != user.id
    ):
        raise ForbiddenError("You can only read the history of your own reports.")
    return await audit_service.list_for_complaint(db, complaint_id)


@router.patch(
    "/{complaint_id}/status",
    response_model=ComplaintPublic,
    status_code=status.HTTP_200_OK,
    summary="Transition a complaint",
    description=(
        "Officer/admin workflow transitions. `resolved` requires a passed image "
        "verification; `closed` is reached by citizen confirmation (or admin action). "
        "Every transition is audited and notifies the reporter."
    ),
    responses={
        200: {"description": "Status updated."},
        400: {"description": "Illegal transition."},
        401: {"description": "Not authenticated."},
        403: {"description": "Not allowed for this role or ward."},
        404: {"description": "Unknown complaint id."},
        409: {"description": "Already in that state or verification missing."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def change_status(
    complaint_id: str,
    payload: ComplaintUpdateStatus,
    user: CurrentUserDep,
    db: DbDep,
) -> ComplaintPublic:
    if user.role == Role.CITIZEN:
        raise ForbiddenError("Citizens cannot change complaint status.")
    return await service.update_status(db, complaint_id, payload.status, payload.note, user)


@router.post(
    "/{complaint_id}/vote",
    response_model=ComplaintPublic,
    status_code=status.HTTP_200_OK,
    summary="Upvote a complaint",
    description=(
        "Support an existing issue instead of filing a duplicate. Idempotent: voting "
        "twice keeps a single vote. Votes feed the priority score's frequency term."
    ),
    responses={
        200: {"description": "Vote recorded (or already present)."},
        401: {"description": "Not authenticated."},
        404: {"description": "Unknown complaint id."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def upvote(complaint_id: str, user: CurrentUserDep, db: DbDep) -> ComplaintPublic:
    return await service.vote(db, complaint_id, user, add=True)


@router.delete(
    "/{complaint_id}/vote",
    response_model=ComplaintPublic,
    status_code=status.HTTP_200_OK,
    summary="Withdraw an upvote",
    responses={
        200: {"description": "Vote withdrawn (or was absent)."},
        401: {"description": "Not authenticated."},
        404: {"description": "Unknown complaint id."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def remove_vote(complaint_id: str, user: CurrentUserDep, db: DbDep) -> ComplaintPublic:
    return await service.vote(db, complaint_id, user, add=False)


@router.post(
    "/{complaint_id}/attachments",
    response_model=ComplaintPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a photo",
    description=(
        "Upload a JPEG/PNG/WebP/TIFF/BMP photo (max 8 MB). `kind=before` marks the "
        "pre-repair evidence required for resolution verification; `kind=after` is "
        "reserved for the resolution endpoint."
    ),
    responses={
        201: {"description": "Photo stored and linked."},
        400: {"description": "Empty file or invalid kind."},
        401: {"description": "Not authenticated."},
        403: {"description": "Not allowed for this complaint."},
        409: {"description": "Attachment limit reached."},
        413: {"description": "Photo exceeds the 8 MB limit."},
        415: {"description": "Unsupported image type."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def add_attachment(
    complaint_id: str,
    user: CurrentUserDep,
    db: DbDep,
    file: Annotated[UploadFile, File(description="Photo evidence.")],
    kind: Annotated[Literal["before", "general"], Form()] = "general",
) -> ComplaintPublic:
    data = await file.read()
    content_type = validate_upload(
        content_type=file.content_type,
        data=data,
        allowed=ALLOWED_IMAGE_TYPES,
        max_bytes=MAX_IMAGE_BYTES,
        kind="image",
    )
    await service.add_attachment(
        db,
        complaint_id,
        kind=kind,
        filename=file.filename or "photo",
        content_type=content_type,
        data=data,
        actor=user,
    )
    return await service.get_complaint(db, complaint_id, user)


@router.post(
    "/{complaint_id}/resolution",
    response_model=ComplaintPublic,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an after-photo for verification",
    description=(
        "Officer uploads the completed-work photo. The before/after comparison "
        "(CLIP scene similarity + SSIM and defect-delta features through a trained "
        "comparator) runs asynchronously; on a pass the complaint becomes `resolved` "
        "and the reporter is asked to confirm or dispute."
    ),
    responses={
        202: {"description": "After-photo stored and verification queued."},
        400: {"description": "Empty/invalid upload."},
        401: {"description": "Not authenticated."},
        403: {"description": "Not allowed for this complaint."},
        409: {"description": "Wrong status or missing before-photo."},
        415: {"description": "Unsupported image type."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def submit_resolution(
    complaint_id: str,
    user: CurrentUserDep,
    db: DbDep,
    file: Annotated[UploadFile, File(description="Photo of the completed work.")],
    note: Annotated[str | None, Form(max_length=500)] = None,
) -> ComplaintPublic:
    data = await file.read()
    content_type = validate_upload(
        content_type=file.content_type,
        data=data,
        allowed=ALLOWED_IMAGE_TYPES,
        max_bytes=MAX_IMAGE_BYTES,
        kind="image",
    )
    ref: AttachmentRef = await service.add_attachment(
        db,
        complaint_id,
        kind="after",
        filename=file.filename or "after.jpg",
        content_type=content_type,
        data=data,
        actor=user,
    )
    await service.request_resolution(db, complaint_id, after_media_id=ref.id, note=note, actor=user)
    verify_resolution.delay(complaint_id, ref.id, user.id)
    return await service.get_complaint(db, complaint_id, user)


@router.post(
    "/{complaint_id}/resolution/confirm",
    response_model=ComplaintPublic,
    status_code=status.HTTP_200_OK,
    summary="Confirm the fix (closes the complaint)",
    description="The reporter accepts the verified resolution; the complaint is closed.",
    responses={
        200: {"description": "Resolution confirmed; complaint closed."},
        401: {"description": "Not authenticated."},
        403: {"description": "Only the reporter may decide."},
        404: {"description": "Unknown complaint id."},
        409: {"description": "Not resolved or not verification-passed."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def confirm_resolution(
    complaint_id: str,
    payload: ResolutionDecision,
    user: CurrentUserDep,
    db: DbDep,
) -> ComplaintPublic:
    return await service.record_citizen_decision(
        db, complaint_id, decision="confirmed", note=payload.note, citizen=user
    )


@router.post(
    "/{complaint_id}/resolution/dispute",
    response_model=ComplaintPublic,
    status_code=status.HTTP_200_OK,
    summary="Dispute the fix (reopens the complaint)",
    description=(
        "The reporter rejects the verified resolution; the complaint returns to "
        "`in_progress` and the assigned officer is notified."
    ),
    responses={
        200: {"description": "Resolution disputed; complaint reopened."},
        401: {"description": "Not authenticated."},
        403: {"description": "Only the reporter may decide."},
        404: {"description": "Unknown complaint id."},
        409: {"description": "Not resolved or not verification-passed."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def dispute_resolution(
    complaint_id: str,
    payload: ResolutionDecision,
    user: CurrentUserDep,
    db: DbDep,
) -> ComplaintPublic:
    return await service.record_citizen_decision(
        db, complaint_id, decision="disputed", note=payload.note, citizen=user
    )
