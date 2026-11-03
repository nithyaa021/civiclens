"""Version-1 API router: aggregates every v1 endpoint module."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, health, jobs, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(jobs.router)
