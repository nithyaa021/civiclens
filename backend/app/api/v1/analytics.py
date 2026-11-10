"""Authority dashboard aggregations: overview KPIs and map points."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import CurrentUserDep, DbDep
from app.models.analytics import ComplaintMapResponse, OverviewResponse
from app.models.complaint import ComplaintStatus
from app.services import analytics as service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/overview",
    response_model=OverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Authority overview KPIs, trend and category mix",
    description=(
        "Aggregated from live complaint records. Admins see all wards; ward "
        "officers see only their assigned ward."
    ),
    responses={
        200: {"description": "Overview for the caller's scope."},
        401: {"description": "Not authenticated."},
        403: {"description": "Citizens cannot open the authority overview."},
    },
)
async def overview(
    user: CurrentUserDep,
    db: DbDep,
    period_days: Annotated[int, Query(ge=7, le=180)] = 30,
) -> OverviewResponse:
    return await service.overview(db, user, period_days=period_days)


@router.get(
    "/map",
    response_model=ComplaintMapResponse,
    status_code=status.HTTP_200_OK,
    summary="Lightweight complaint points for the map",
    description=(
        "Up to 1,500 points ordered by priority score, with the role scope applied. "
        "The `truncated` flag is true when more records exist than were returned."
    ),
    responses={
        200: {"description": "Map points."},
        401: {"description": "Not authenticated."},
        403: {"description": "Citizens cannot open the authority map."},
    },
)
async def complaint_map(
    user: CurrentUserDep,
    db: DbDep,
    category: Annotated[str | None, Query(max_length=40)] = None,
    status_filter: Annotated[ComplaintStatus | None, Query(alias="status")] = None,
    ward: Annotated[int | None, Query(ge=1, le=999)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 1500,
) -> ComplaintMapResponse:
    return await service.complaint_map(
        db, user, category=category, status=status_filter, ward=ward, limit=limit
    )
