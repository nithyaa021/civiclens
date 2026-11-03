"""Sliding-window rate limiting backed by Redis.

Uses a sorted set per key where members are request timestamps (ms).  A single
Lua script performs read-shift-add atomically so concurrent requests cannot
race past the limit.

If Redis is unavailable the limiter **fails open** (allows traffic) and logs a
warning - an outage should not take the API down.
"""

from __future__ import annotations

import time
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.errors import RateLimitExceeded
from app.core.logging import get_logger

logger = get_logger("civiclens.rate_limit")

# KEYS[1] = zset key
# ARGV[1] = window cutoff (ms) - entries older than this are dropped
# ARGV[2] = now (ms)
# ARGV[3] = max requests per window
# ARGV[4] = unique member for this request
# ARGV[5] = key TTL (ms)
# ARGV[6] = window length (ms)
# Returns {allowed (0/1), remaining, retry_after_ms}
_SLIDING_WINDOW_SCRIPT = """
local cutoff = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local ttl = tonumber(ARGV[5])
local window = tonumber(ARGV[6])

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
local used = redis.call('ZCARD', KEYS[1])

if used < limit then
    redis.call('ZADD', KEYS[1], now, ARGV[4])
    redis.call('PEXPIRE', KEYS[1], ttl)
    return {1, limit - used - 1, 0}
end

-- Over the limit: report when the oldest entry ages out of the window.
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local retry_after_ms = window
if oldest[2] then
    retry_after_ms = math.max(0, tonumber(oldest[2]) + window - now)
end
return {0, 0, retry_after_ms}
"""


class RateLimitResult:
    """Outcome of a single rate-limit check."""

    __slots__ = ("allowed", "remaining", "retry_after_seconds", "limit", "window_seconds")

    def __init__(
        self,
        *,
        allowed: bool,
        remaining: int,
        retry_after_seconds: int,
        limit: int,
        window_seconds: int,
    ) -> None:
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after_seconds = retry_after_seconds
        self.limit = limit
        self.window_seconds = window_seconds


class RateLimiter:
    """Sliding-window limiter over a Redis connection."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_SLIDING_WINDOW_SCRIPT)

    async def hit(self, *, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Record a request for ``key`` and report whether it is allowed."""
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - window_seconds * 1000
        ttl_ms = window_seconds * 1000 + 1000
        try:
            raw = await self._script(
                keys=[f"ratelimit:{key}"],
                args=[cutoff_ms, now_ms, limit, uuid.uuid4().hex, ttl_ms, window_seconds * 1000],
            )
        except RedisError as exc:
            logger.warning("rate_limit_unavailable", key=key, error=str(exc))
            return RateLimitResult(
                allowed=True,
                remaining=limit,
                retry_after_seconds=0,
                limit=limit,
                window_seconds=window_seconds,
            )

        allowed, remaining, retry_after_ms = (int(raw[0]), int(raw[1]), int(raw[2]))
        return RateLimitResult(
            allowed=bool(allowed),
            remaining=max(0, remaining),
            retry_after_seconds=int(retry_after_ms // 1000) if retry_after_ms else 0,
            limit=limit,
            window_seconds=window_seconds,
        )

    async def enforce(
        self, *, key: str, limit: int, window_seconds: int, subject: str | None = None
    ) -> RateLimitResult:
        """``hit`` + raise :class:`RateLimitExceeded` when over the limit."""
        identity = subject or "anonymous"
        result = await self.hit(key=f"{key}:{identity}", limit=limit, window_seconds=window_seconds)
        if not result.allowed:
            raise RateLimitExceeded(
                retry_after_seconds=result.retry_after_seconds,
                limit=limit,
                window_seconds=window_seconds,
            )
        return result
