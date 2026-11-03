"""MongoDB (Motor) and Redis connection management."""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings, get_settings

_mongo_client: AsyncIOMotorClient | None = None
_redis_client: Redis | None = None


def get_mongo_client() -> AsyncIOMotorClient:
    """Return (creating on first use) the shared async MongoDB client."""
    global _mongo_client
    if _mongo_client is None:
        settings = get_settings()
        _mongo_client = AsyncIOMotorClient(
            settings.mongo_uri,
            serverSelectionTimeoutMS=3000,
            tz_aware=True,
        )
    return _mongo_client


def get_database(settings: Settings | None = None) -> AsyncIOMotorDatabase:
    """Return the configured MongoDB database handle."""
    settings = settings or get_settings()
    return get_mongo_client()[settings.mongo_db]


def get_redis() -> Redis:
    """Return (creating on first use) the shared async Redis client."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=3,
            socket_timeout=3,
            decode_responses=True,
            # RESP2: compatible with Redis >= 5 through 7 (HELLO/RESP3 needs 6+).
            protocol=2,
        )
    return _redis_client


async def ping_mongo() -> None:
    """Raise when MongoDB is unreachable."""
    await get_mongo_client().admin.command("ping")


async def ping_redis() -> None:
    """Raise when Redis is unreachable."""
    await get_redis().ping()


async def close_resources() -> None:
    """Close both connection pools during application shutdown."""
    global _mongo_client, _redis_client
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def probe(check: Any, *args: Any, **kwargs: Any) -> tuple[bool, float, str | None]:
    """Run an async health probe; returns ``(ok, latency_ms, error_detail)``."""
    import time

    start = time.perf_counter()
    try:
        await check(*args, **kwargs)
        return True, round((time.perf_counter() - start) * 1000, 2), None
    except TimeoutError:
        return False, round((time.perf_counter() - start) * 1000, 2), "timeout"
    except Exception as exc:  # noqa: BLE001 - health probes must never raise
        return False, round((time.perf_counter() - start) * 1000, 2), f"{type(exc).__name__}: {exc}"
