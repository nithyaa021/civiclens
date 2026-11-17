"""Authentication business logic: registration, login, token rotation.

Refresh tokens are single-use.  Each issued refresh ``jti`` is stored in Redis
with the token's TTL; rotating or logging out deletes it, so a stolen refresh
token can be replayed at most once before it is rejected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.token import TokenResponse
from app.models.user import Role, UserPublic, UserRegister, UserStatus

REFRESH_JTI_PREFIX = "auth:refresh:"


def serialize_doc(doc: dict[str, Any]) -> UserPublic:
    return UserPublic(
        id=str(doc["_id"]),
        email=doc["email"],
        full_name=doc["full_name"],
        role=Role(doc["role"]),
        ward=doc.get("ward"),
        status=UserStatus(doc.get("status", UserStatus.ACTIVE.value)),
        created_at=doc["created_at"],
    )


async def _find_by_email(db: AsyncIOMotorDatabase, email: str) -> dict[str, Any] | None:
    return await db["users"].find_one({"email": email.strip().lower()})


async def register_user(
    db: AsyncIOMotorDatabase,
    payload: UserRegister,
    *,
    role: Role = Role.CITIZEN,
    ward: int | None = None,
) -> UserPublic:
    """Create a citizen account (or a provisioned account when called by admin code)."""
    email = payload.email.strip().lower()
    if await _find_by_email(db, email):
        raise ConflictError(
            "An account with this email already exists.",
            details={"field": "email"},
        )
    doc = {
        "email": email,
        "full_name": payload.full_name.strip(),
        "password_hash": hash_password(payload.password),
        "role": role.value,
        "ward": ward,
        "status": UserStatus.ACTIVE.value,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    result = await db["users"].insert_one(doc)
    doc["_id"] = result.inserted_id
    return serialize_doc(doc)


async def authenticate(db: AsyncIOMotorDatabase, email: str, password: str) -> UserPublic:
    """Verify credentials; raises :class:`UnauthorizedError` on any failure.

    Generic messages deliberately avoid revealing whether the email exists.
    """
    doc = await _find_by_email(db, email)
    if doc is None:
        # Run a dummy verify to equalise timing between unknown/known emails.
        verify_password(
            "$argon2id$v=19$m=65536,t=2,p=1$c29tZXNhbHRzb21lc2FsdA$0000000000000000000000000000000000000000000",
            password,
        )
        raise UnauthorizedError("Invalid email or password.", code="invalid_credentials")

    if not verify_password(doc["password_hash"], password):
        raise UnauthorizedError("Invalid email or password.", code="invalid_credentials")

    if doc.get("status") != UserStatus.ACTIVE.value:
        raise UnauthorizedError("Account is deactivated.", code="user_inactive")

    if needs_rehash(doc["password_hash"]):
        await db["users"].update_one(
            {"_id": doc["_id"]},
            {"$set": {"password_hash": hash_password(password), "updated_at": datetime.now(UTC)}},
        )

    return serialize_doc(doc)


async def _store_refresh_jti(redis: Redis, jti: str, user_id: str, expires_days: int) -> None:
    await redis.set(f"{REFRESH_JTI_PREFIX}{jti}", user_id, ex=expires_days * 24 * 3600)


async def _consume_refresh_jti(redis: Redis, jti: str, expected_user_id: str) -> bool:
    """Atomically claim a refresh jti; returns False when unknown/reused."""
    key = f"{REFRESH_JTI_PREFIX}{jti}"
    stored_user = await redis.get(key)
    if stored_user is None or stored_user != expected_user_id:
        return False
    await redis.delete(key)
    return True


async def issue_tokens(
    db: AsyncIOMotorDatabase,
    redis: Redis,
    settings: Settings,
    user: UserPublic,
) -> TokenResponse:
    """Create a fresh access + refresh token pair for ``user``."""
    access_token, _ = create_access_token(
        subject=user.id,
        role=user.role,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.access_token_expire_minutes,
    )
    refresh_token, refresh_jti = create_refresh_token(
        subject=user.id,
        role=user.role,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_days=settings.refresh_token_expire_days,
    )
    await _store_refresh_jti(redis, refresh_jti, user.id, settings.refresh_token_expire_days)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
        refresh_expires_in=settings.refresh_token_expire_days * 24 * 3600,
        user=user,
    )


async def _load_active_user(db: AsyncIOMotorDatabase, user_id: str) -> UserPublic:
    try:
        doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    except InvalidId as exc:
        raise UnauthorizedError(
            "Token subject is not a valid user id.", code="token_invalid"
        ) from exc
    if doc is None:
        raise UnauthorizedError("Account no longer exists.", code="user_not_found")
    if doc.get("status") != UserStatus.ACTIVE.value:
        raise UnauthorizedError("Account is deactivated.", code="user_inactive")
    return serialize_doc(doc)


async def refresh_tokens(
    db: AsyncIOMotorDatabase,
    redis: Redis,
    settings: Settings,
    refresh_token: str,
) -> TokenResponse:
    """Rotate a refresh token: consume the old jti and issue a new pair.

    Raises:
        UnauthorizedError: when the token is expired/invalid, or when its jti
            has already been rotated or revoked (replay attempt).
    """
    payload = decode_token(
        refresh_token,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expected_type="refresh",
    )
    user = await _load_active_user(db, payload.sub)
    if not await _consume_refresh_jti(redis, payload.jti, user.id):
        raise UnauthorizedError(
            "Refresh token has been revoked or already used.", code="refresh_revoked"
        )
    return await issue_tokens(db, redis, settings, user)


async def logout(
    redis: Redis,
    refresh_token: str,
    settings: Settings,
) -> None:
    """Revoke a refresh token (idempotent from the client's perspective)."""
    payload = decode_token(
        refresh_token,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expected_type="refresh",
    )
    await redis.delete(f"{REFRESH_JTI_PREFIX}{payload.jti}")


async def revoke_all_for_user(db: AsyncIOMotorDatabase, redis: Redis, user_id: str) -> int:
    """Revoke every refresh token of a user (admin force-logout / deactivation)."""
    # Refresh jtis are stored as `auth:refresh:{jti}` -> user_id; scan is used
    # because the jti is not derivable from the user id.
    revoked = 0
    async for key in redis.scan_iter(match=f"{REFRESH_JTI_PREFIX}*"):
        if await redis.get(key) == user_id:
            await redis.delete(key)
            revoked += 1
    await db["users"].update_one(
        {"_id": ObjectId(user_id)} if ObjectId.is_valid(user_id) else {"email": "__no_match__"},
        {"$set": {"updated_at": datetime.now(UTC)}},
    )
    return revoked
