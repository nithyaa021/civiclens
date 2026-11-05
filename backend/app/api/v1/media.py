"""Media retrieval for evidence photos."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.deps import CurrentUserDep, DbDep
from app.core.errors import ForbiddenError, NotFoundError
from app.models.user import Role

router = APIRouter(prefix="/media", tags=["media"])


@router.get(
    "/{media_id}",
    response_class=Response,
    status_code=status.HTTP_200_OK,
    summary="Download a stored photo",
    description=(
        "Streams the original bytes. The uploader, the complaint's reporter, the "
        "ward's officer and admins may read a photo; everyone else gets 403."
    ),
    responses={
        200: {"description": "Image bytes."},
        401: {"description": "Not authenticated."},
        403: {"description": "Not allowed to read this photo."},
        404: {"description": "Unknown media id."},
    },
)
async def get_media(
    media_id: str,
    user: CurrentUserDep,
    db: DbDep,
    download: Annotated[bool, Query(description="Send as attachment.")] = False,
) -> Response:
    from bson import ObjectId

    if not ObjectId.is_valid(media_id):
        raise NotFoundError("Media", media_id)
    media = await db["media"].find_one({"_id": ObjectId(media_id)})
    if media is None:
        raise NotFoundError("Media", media_id)

    allowed = user.role in (Role.ADMIN, Role.WARD_OFFICER) or media.get("owner_id") == user.id
    complaint_id = media.get("complaint_id")
    if not allowed and complaint_id:
        from bson import ObjectId as Oid

        if Oid.is_valid(complaint_id):
            complaint = await db["complaints"].find_one(
                {"_id": Oid(complaint_id)}, {"citizen_id": 1, "ward": 1}
            )
            if complaint is not None:
                allowed = complaint.get("citizen_id") == user.id or (
                    user.role == Role.WARD_OFFICER and complaint.get("ward") == user.ward
                )
    if not allowed:
        raise ForbiddenError("You are not allowed to read this photo.")

    disposition = "attachment" if download else "inline"
    filename = str(media.get("filename") or f"{media_id}.bin").replace('"', "")
    return Response(
        content=media["data"],
        media_type=media.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.get(
    "/{media_id}/meta",
    status_code=status.HTTP_200_OK,
    summary="Photo metadata",
    description="Content type, size, purpose and upload time (no bytes).",
    responses={
        200: {"description": "Metadata."},
        401: {"description": "Not authenticated."},
        403: {"description": "Not allowed."},
        404: {"description": "Unknown media id."},
    },
)
async def get_media_meta(media_id: str, user: CurrentUserDep, db: DbDep) -> dict:
    from bson import ObjectId

    if not ObjectId.is_valid(media_id):
        raise NotFoundError("Media", media_id)
    media = await db["media"].find_one(
        {"_id": ObjectId(media_id)},
        {"data": 0},
    )
    if media is None:
        raise NotFoundError("Media", media_id)
    if user.role not in (Role.ADMIN, Role.WARD_OFFICER) and media.get("owner_id") != user.id:
        raise ForbiddenError("You are not allowed to read this photo.")
    return {
        "id": str(media["_id"]),
        "filename": media.get("filename"),
        "content_type": media.get("content_type"),
        "size_bytes": media.get("size_bytes"),
        "purpose": media.get("purpose"),
        "complaint_id": media.get("complaint_id"),
        "created_at": media["created_at"].isoformat(),
    }
