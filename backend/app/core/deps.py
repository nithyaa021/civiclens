"""Reusable FastAPI dependencies: settings, DB, auth, RBAC, rate limiting."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.rate_limit import RateLimiter
from app.core.security import decode_token
from app.db.mongo import get_database, get_redis
from app.models.user import Role, UserPublic


# --- Infrastructure -----------------------------------------------------------
async def db_dep(settings: Annotated[Settings, Depends(get_settings)]) -> AsyncIOMotorDatabase:
    """Application database handle."""
    return get_database(settings)


def redis_dep() -> Redis:
    """Application Redis handle."""
    return get_redis()


def limiter_dep() -> RateLimiter:
    """Rate limiter bound to the shared Redis connection."""
    return RateLimiter(get_redis())


# --- Authentication -----------------------------------------------------------
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    scheme_name="OAuth2Password",
    description="Paste the `access_token` returned by **POST /api/v1/auth/login**.",
)

CredentialsDep = Annotated[str, Depends(oauth2_scheme)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncIOMotorDatabase, Depends(db_dep)]
RedisDep = Annotated[Redis, Depends(redis_dep)]
LimiterDep = Annotated[RateLimiter, Depends(limiter_dep)]


async def get_current_user(
    token: CredentialsDep,
    db: DbDep,
    settings: SettingsDep,
) -> UserPublic:
    """Resolve the request's Bearer access token to an active user.

    Raises:
        UnauthorizedError: expired/invalid token, wrong token type, unknown or
            deactivated account.
    """
    from bson import ObjectId
    from bson.errors import InvalidId

    payload = decode_token(
        token,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expected_type="access",
    )
    try:
        user_id = ObjectId(payload.sub)
    except InvalidId as exc:
        raise UnauthorizedError(
            "Token subject is not a valid user id.", code="token_invalid"
        ) from exc

    doc = await db["users"].find_one({"_id": user_id})
    if doc is None:
        raise UnauthorizedError("Account no longer exists.", code="user_not_found")
    if doc.get("status") != "active":
        raise UnauthorizedError("Account is deactivated.", code="user_inactive")

    return UserPublic(
        id=str(doc["_id"]),
        email=doc["email"],
        full_name=doc["full_name"],
        role=Role(doc["role"]),
        ward=doc.get("ward"),
        status=doc["status"],
        created_at=doc["created_at"],
    )


CurrentUserDep = Annotated[UserPublic, Depends(get_current_user)]


def require_roles(*allowed_roles: Role) -> Callable[..., Awaitable[UserPublic]]:
    """Role guard factory.

    ``admin`` implicitly satisfies every guard; other roles must be listed
    explicitly.  Example::

        @router.get("/wards", dependencies=[Depends(require_roles(Role.WARD_OFFICER))])
    """
    allowed = set(allowed_roles)

    async def _guard(user: CurrentUserDep) -> UserPublic:
        if user.role == Role.ADMIN or user.role in allowed:
            return user
        raise ForbiddenError(
            f"This endpoint requires role: {', '.join(sorted(r.value for r in allowed))}."
        )

    return _guard


# --- Rate limiting ------------------------------------------------------------
def rate_limit(
    bucket: str, limit_setting: str, window_setting: str
) -> Callable[..., Awaitable[None]]:
    """Build a route dependency that enforces a named rate-limit bucket.

    Identity is the authenticated user id when a valid access token is present,
    otherwise the client IP.  Buckets read their limit/window from Settings.
    """

    async def _dependency(
        request: Request,
        settings: SettingsDep,
        limiter: LimiterDep,
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        limit = int(getattr(settings, limit_setting))
        window = int(getattr(settings, window_setting))
        subject = _identity(request)
        request.state.rate_limit_remaining = None  # populated below on success
        result = await limiter.enforce(
            key=bucket,
            limit=limit,
            window_seconds=window,
            subject=subject,
        )
        request.state.rate_limit_remaining = result.remaining

    return _dependency


def _identity(request: Request) -> str:
    """Best-effort caller identity: token subject (verified) or client IP."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        # Verified decode only - unauthenticated/invalid tokens fall back to IP.
        from app.core.errors import ApiError

        try:
            settings = get_settings()
            payload = decode_token(
                header[7:].strip(),
                secret=settings.jwt_secret,
                algorithm=settings.jwt_algorithm,
                expected_type="access",
            )
            return f"user:{payload.sub}"
        except ApiError:
            pass
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


# Convenience instances used by the routers.
default_rate_limit = rate_limit(
    "api",
    "rate_limit_default_limit",
    "rate_limit_default_window_seconds",
)
auth_rate_limit = rate_limit(
    "auth",
    "rate_limit_auth_limit",
    "rate_limit_auth_window_seconds",
)


def as_dependency(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Identity helper kept for explicit route wiring readability."""
    return fn
