"""Version-1 API router: aggregates every v1 endpoint module."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    analytics,
    assistant,
    auth,
    clusters,
    complaints,
    forecasts,
    health,
    jobs,
    media,
    public,
    users,
    voice,
    wards,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(jobs.router)
api_router.include_router(wards.router)
api_router.include_router(complaints.router)
api_router.include_router(clusters.router)
api_router.include_router(forecasts.router)
api_router.include_router(analytics.router)
api_router.include_router(assistant.router)
api_router.include_router(voice.router)
api_router.include_router(media.router)
api_router.include_router(public.router)
