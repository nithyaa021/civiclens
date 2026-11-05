"""Recurring-issue cluster endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import (
    CurrentUserDep,
    DbDep,
    SettingsDep,
    default_rate_limit,
    require_roles,
)
from app.models.complaint import ClusterResponse, ComplaintSummary
from app.models.user import Role
from app.services import clusters as service

router = APIRouter(prefix="/clusters", tags=["clusters"])

staff_only = Depends(require_roles(Role.WARD_OFFICER))


@router.get(
    "/recurring",
    response_model=ClusterResponse,
    status_code=status.HTTP_200_OK,
    summary="List recurring issues",
    description=(
        "Geospatial + semantic clusters (DBSCAN over combined haversine and "
        "embedding distance, per category) with report count, first/last report, "
        "affected area and member complaint ids."
    ),
    responses={
        200: {"description": "Clusters, largest first."},
        401: {"description": "Not authenticated."},
    },
)
async def list_recurring(
    user: CurrentUserDep,
    db: DbDep,
    settings: SettingsDep,
    category: Annotated[str | None, Query(max_length=40)] = None,
    ward: Annotated[int | None, Query(ge=1, le=999)] = None,
    min_count: Annotated[int, Query(ge=1, le=1000)] = 2,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ClusterResponse:
    items = await service.list_clusters(
        db, category=category, ward=ward, min_count=min_count, limit=limit
    )
    return ClusterResponse(
        items=items, lookback_days=settings.cluster_lookback_days, computed_at=datetime.now(UTC)
    )


@router.post(
    "/recompute",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Recompute clusters and priority scores",
    description=(
        "Rebuilds recurring-issue clusters and refreshes stored priority scores from "
        "the current embeddings. Staff only; the Celery beat schedule runs the same "
        "computation every 30 minutes."
    ),
    responses={
        202: {"description": "Recomputation finished; summary returned."},
        401: {"description": "Not authenticated."},
        403: {"description": "Staff only."},
    },
    dependencies=[staff_only, Depends(default_rate_limit)],
)
async def recompute(db: DbDep, settings: SettingsDep) -> dict:
    return await service.recompute(db, settings)


@router.get(
    "/recurring/{cluster_id}/members",
    response_model=list[ComplaintSummary],
    status_code=status.HTTP_200_OK,
    summary="List a cluster's member complaints",
    responses={
        200: {"description": "Member complaint cards in cluster order."},
        401: {"description": "Not authenticated."},
        404: {"description": "Unknown cluster id (recompute may have replaced it)."},
    },
)
async def cluster_members(
    cluster_id: str, user: CurrentUserDep, db: DbDep
) -> list[ComplaintSummary]:
    from app.core.errors import NotFoundError

    doc = await db["clusters"].find_one({"_id": cluster_id})
    if doc is None:
        raise NotFoundError("Cluster", cluster_id)
    return await service.cluster_members(db, [str(cid) for cid in doc["complaint_ids"]])
