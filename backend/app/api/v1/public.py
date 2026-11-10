"""Public transparency endpoints. No authentication, no personal data."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.deps import DbDep
from app.models.analytics import PublicStats
from app.services import analytics as service

router = APIRouter(prefix="/public", tags=["public"])


@router.get(
    "/stats",
    response_model=PublicStats,
    status_code=status.HTTP_200_OK,
    summary="Anonymised city-wide transparency statistics",
    description=(
        "Aggregate resolution performance per ward and category. Reporter identity, "
        "officer identity and exact coordinates are never included. Cached for 60 "
        "seconds by the browser."
    ),
    response_model_exclude_none=False,
    responses={200: {"description": "Public statistics."}},
)
async def public_stats(db: DbDep, response: Response) -> PublicStats:
    response.headers["Cache-Control"] = "public, max-age=60"
    return await service.public_stats(db)
