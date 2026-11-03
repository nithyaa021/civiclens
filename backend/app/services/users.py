"""User management business logic (admin operations)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.core.errors import ConflictError, NotFoundError
from app.core.security import hash_password
from app.models.common import Page
from app.models.user import (
    Role,
    UserCreate,
    UserPublic,
    UserStatus,
)


def serialize(doc: dict[str, Any]) -> UserPublic:
    """Convert a Mongo user document into :class:`UserPublic`."""
    return UserPublic(
        id=str(doc["_id"]),
        email=doc["email"],
        full_name=doc["full_name"],
        role=Role(doc["role"]),
        ward=doc.get("ward"),
        status=UserStatus(doc.get("status", UserStatus.ACTIVE.value)),
        created_at=doc["created_at"],
    )


async def create_user(db: AsyncIOMotorDatabase, payload: UserCreate) -> UserPublic:
    """Admin-provisioned account creation (ward officers / admins)."""
    email = payload.email.strip().lower()
    existing = await db["users"].find_one({"email": email})
    if existing is not None:
        raise ConflictError(
            "An account with this email already exists.", details={"field": "email"}
        )

    now = datetime.now(UTC)
    doc = {
        "email": email,
        "full_name": payload.full_name.strip(),
        "password_hash": hash_password(payload.password),
        "role": payload.role.value,
        "ward": payload.ward,
        "status": UserStatus.ACTIVE.value,
        "created_at": now,
        "updated_at": now,
    }
    result = await db["users"].insert_one(doc)
    doc["_id"] = result.inserted_id
    return serialize(doc)


async def get_user(db: AsyncIOMotorDatabase, user_id: str) -> UserPublic:
    """Fetch one user by id or raise :class:`NotFoundError`."""
    if not ObjectId.is_valid(user_id):
        raise NotFoundError("User", user_id)
    doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    if doc is None:
        raise NotFoundError("User", user_id)
    return serialize(doc)


async def list_users(
    db: AsyncIOMotorDatabase,
    *,
    page: int,
    page_size: int,
    role: Role | None = None,
    status: UserStatus | None = None,
    search: str | None = None,
) -> Page[UserPublic]:
    """Paginated, filterable user listing."""
    query: dict[str, Any] = {}
    if role is not None:
        query["role"] = role.value
    if status is not None:
        query["status"] = status.value
    if search:
        # Prefix search over the two human-facing fields.
        regex = {"$regex": search.strip(), "$options": "i"}
        query["$or"] = [{"email": regex}, {"full_name": regex}]

    total = await db["users"].count_documents(query)
    cursor = (
        db["users"].find(query).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size)
    )
    items = [serialize(doc) async for doc in cursor]
    return Page[UserPublic](items=items, total=total, page=page, page_size=page_size)


async def update_role(
    db: AsyncIOMotorDatabase, user_id: str, new_role: Role, *, actor_id: str
) -> UserPublic:
    """Change a user's role, refusing to remove the last active admin."""
    if not ObjectId.is_valid(user_id):
        raise NotFoundError("User", user_id)

    current = await db["users"].find_one({"_id": ObjectId(user_id)})
    if current is None:
        raise NotFoundError("User", user_id)

    if current["role"] == Role.ADMIN.value and new_role != Role.ADMIN:
        remaining = await db["users"].count_documents(
            {"role": Role.ADMIN.value, "status": UserStatus.ACTIVE.value}
        )
        if remaining <= 1:
            raise ConflictError(
                "Cannot demote the last active administrator.",
                details={"reason": "last_admin"},
            )

    if new_role == Role.WARD_OFFICER and current.get("ward") is None:
        raise ConflictError(
            "Assign a ward before promoting this account to ward_officer.",
            details={"field": "ward"},
        )

    updated = await db["users"].find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$set": {"role": new_role.value, "updated_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    assert updated is not None  # guarded by the lookup above
    _ = actor_id  # audit hook point: callers pass the acting admin id
    return serialize(updated)


async def update_status(
    db: AsyncIOMotorDatabase, user_id: str, new_status: UserStatus, *, actor_id: str
) -> UserPublic:
    """Activate/deactivate an account, refusing self-deactivation."""
    if not ObjectId.is_valid(user_id):
        raise NotFoundError("User", user_id)

    current = await db["users"].find_one({"_id": ObjectId(user_id)})
    if current is None:
        raise NotFoundError("User", user_id)

    if actor_id == user_id and new_status == UserStatus.INACTIVE:
        raise ConflictError("You cannot deactivate your own account.", details={"reason": "self"})

    if current["role"] == Role.ADMIN.value and new_status == UserStatus.INACTIVE:
        remaining = await db["users"].count_documents(
            {"role": Role.ADMIN.value, "status": UserStatus.ACTIVE.value}
        )
        if remaining <= 1:
            raise ConflictError(
                "Cannot deactivate the last active administrator.",
                details={"reason": "last_admin"},
            )

    updated = await db["users"].find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$set": {"status": new_status.value, "updated_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    assert updated is not None
    return serialize(updated)


async def count_users(db: AsyncIOMotorDatabase) -> int:
    """Total number of accounts (used by admin dashboards and seeding checks)."""
    return await db["users"].count_documents({})
