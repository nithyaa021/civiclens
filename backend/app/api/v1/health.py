"""Health and readiness endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response, status

from app.core.deps import SettingsDep
from app.db.mongo import ping_mongo, ping_redis, probe
from app.models.common import DependencyStatus, HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness probe with dependency checks",
    description=(
        "Pings MongoDB and Redis and reports per-dependency latency. Returns "
        "`503 Service Unavailable` when any critical dependency is down, so "
        "load balancers and orchestrators can act on it."
    ),
    responses={
        200: {"description": "All dependencies reachable."},
        503: {"description": "At least one dependency unreachable."},
    },
)
async def readiness(response: Response, settings: SettingsDep) -> HealthResponse:
    mongo_ok, mongo_ms, mongo_detail = await probe(ping_mongo)
    redis_ok, redis_ms, redis_detail = await probe(ping_redis)

    dependencies: dict[str, DependencyStatus] = {
        "mongo": DependencyStatus(
            status="ok" if mongo_ok else "error",
            latency_ms=mongo_ms,
            detail=mongo_detail,
        ),
        "redis": DependencyStatus(
            status="ok" if redis_ok else "error",
            latency_ms=redis_ms,
            detail=redis_detail,
        ),
    }
    healthy = mongo_ok and redis_ok
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if healthy else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        time=datetime.now(UTC),
        dependencies=dependencies,
    )


@router.get(
    "/live",
    summary="Liveness probe",
    description="Cheap process-liveness check that touches no dependencies.",
    responses={200: {"description": "Process is alive."}},
)
async def liveness(settings: SettingsDep) -> dict[str, Any]:
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}
