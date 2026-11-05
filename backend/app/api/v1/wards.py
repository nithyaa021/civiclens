"""Ward directory endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core.deps import CurrentUserDep, DbDep
from app.models.ward import WardPublic
from app.services import wards as service

router = APIRouter(prefix="/wards", tags=["wards"])


@router.get(
    "",
    response_model=list[WardPublic],
    status_code=status.HTTP_200_OK,
    summary="List wards",
    description=(
        "Ward boundaries, centroids, sensitive sites (schools/hospitals) and open "
        "complaint counts - the layer rendered by the dashboard map."
    ),
    responses={
        200: {"description": "Wards ordered by number."},
        401: {"description": "Not authenticated."},
    },
)
async def list_wards(user: CurrentUserDep, db: DbDep) -> list[WardPublic]:
    return await service.list_wards(db)


@router.get(
    "/{ward_no}",
    response_model=WardPublic,
    status_code=status.HTTP_200_OK,
    summary="Fetch one ward",
    responses={
        200: {"description": "Ward found."},
        401: {"description": "Not authenticated."},
        404: {"description": "Unknown ward number."},
    },
)
async def get_ward(ward_no: int, user: CurrentUserDep, db: DbDep) -> WardPublic:
    doc = await service.get_ward_by_no(db, ward_no)
    open_count = await db["complaints"].count_documents(
        {"ward": ward_no, "status": {"$in": ["submitted", "assigned", "in_progress"]}}
    )
    return service.ward_public(doc, complaint_count=open_count)
