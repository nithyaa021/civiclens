"""Admin-only user management endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import DbDep, RedisDep, require_roles
from app.core.errors import ForbiddenError
from app.models.common import Page
from app.models.user import (
    OfficerRef,
    Role,
    UserCreate,
    UserPublic,
    UserStatus,
    UserUpdateRole,
    UserUpdateStatus,
)
from app.services import auth as auth_service
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])

admin_only = Depends(require_roles(Role.ADMIN))


@router.post(
    "",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[admin_only],
    summary="Provision a ward officer or admin",
    description=(
        "Admin-only account provisioning. `role` defaults to `ward_officer` and "
        "requires a `ward` number; `admin` role accounts are also allowed."
    ),
    responses={
        201: {"description": "Account created."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller is not an admin."},
        409: {"description": "Email already registered."},
    },
)
async def create_user(payload: UserCreate, db: DbDep) -> UserPublic:
    return await users_service.create_user(db, payload)


@router.get(
    "",
    response_model=Page[UserPublic],
    status_code=status.HTTP_200_OK,
    dependencies=[admin_only],
    summary="List accounts",
    description="Paginated account directory with optional role/status/search filters.",
    responses={
        200: {"description": "Page of accounts."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller is not an admin."},
    },
)
async def list_users(
    db: DbDep,
    page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page.")] = 20,
    role: Annotated[Role | None, Query(description="Filter by role.")] = None,
    status_filter: Annotated[
        UserStatus | None, Query(alias="status", description="Filter by status.")
    ] = None,
    search: Annotated[
        str | None, Query(min_length=1, max_length=80, description="Email/name substring.")
    ] = None,
) -> Page[UserPublic]:
    return await users_service.list_users(
        db,
        page=page,
        page_size=page_size,
        role=role,
        status=status_filter,
        search=search,
    )


@router.get(
    "/officers",
    response_model=list[OfficerRef],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_roles(Role.WARD_OFFICER))],
    summary="List active ward officers",
    description=(
        "Minimal officer directory for assignment pickers. Staff only; email "
        "addresses and account state are not exposed."
    ),
    responses={
        200: {"description": "Active ward officers ordered by ward and name."},
        401: {"description": "Not authenticated."},
        403: {"description": "Staff only."},
    },
)
async def list_officers(
    db: DbDep,
    ward: Annotated[int | None, Query(ge=1, le=999)] = None,
) -> list[OfficerRef]:
    query: dict[str, object] = {"role": Role.WARD_OFFICER.value, "status": UserStatus.ACTIVE.value}
    if ward is not None:
        query["ward"] = ward
    cursor = db["users"].find(query, {"full_name": 1, "ward": 1}).sort(
        [("ward", 1), ("full_name", 1)]
    )
    return [
        OfficerRef(id=str(doc["_id"]), full_name=doc["full_name"], ward=doc.get("ward"))
        async for doc in cursor
    ]


@router.get(
    "/{user_id}",
    response_model=UserPublic,
    status_code=status.HTTP_200_OK,
    dependencies=[admin_only],
    summary="Fetch one account",
    responses={
        200: {"description": "Account found."},
        404: {"description": "Unknown user id."},
    },
)
async def get_user(user_id: str, db: DbDep) -> UserPublic:
    return await users_service.get_user(db, user_id)


@router.patch(
    "/{user_id}/role",
    response_model=UserPublic,
    status_code=status.HTTP_200_OK,
    dependencies=[admin_only],
    summary="Change an account's role",
    description=(
        "Promotes or demotes an account. Guards prevent removing the last active "
        "administrator or promoting a user without a ward to `ward_officer`."
    ),
    responses={
        200: {"description": "Role updated."},
        403: {"description": "Caller is not an admin."},
        404: {"description": "Unknown user id."},
        409: {"description": "Would remove the last admin or ward is missing."},
    },
)
async def change_role(
    user_id: str,
    payload: UserUpdateRole,
    db: DbDep,
    redis: RedisDep,
    current_user: Annotated[UserPublic, Depends(require_roles(Role.ADMIN))],
) -> UserPublic:
    updated = await users_service.update_role(db, user_id, payload.role, actor_id=current_user.id)
    # Role changes invalidate outstanding refresh tokens so the old role
    # cannot be refreshed back into the session.
    await auth_service.revoke_all_for_user(db, redis, user_id)
    return updated


@router.patch(
    "/{user_id}/status",
    response_model=UserPublic,
    status_code=status.HTTP_200_OK,
    dependencies=[admin_only],
    summary="Activate or deactivate an account",
    description=(
        "Deactivated accounts cannot log in and their access tokens are rejected "
        "on the next authenticated request. Self-deactivation and deactivating "
        "the last admin are blocked."
    ),
    responses={
        200: {"description": "Status updated."},
        403: {"description": "Caller is not an admin."},
        404: {"description": "Unknown user id."},
        409: {"description": "Would deactivate yourself or the last admin."},
    },
)
async def change_status(
    user_id: str,
    payload: UserUpdateStatus,
    db: DbDep,
    redis: RedisDep,
    current_user: Annotated[UserPublic, Depends(require_roles(Role.ADMIN))],
) -> UserPublic:
    updated = await users_service.update_status(
        db, user_id, payload.status, actor_id=current_user.id
    )
    if payload.status == UserStatus.INACTIVE:
        await auth_service.revoke_all_for_user(db, redis, user_id)
        if user_id == current_user.id:  # pragma: no cover - guarded above
            raise ForbiddenError("Self-deactivation is not allowed.")
    return updated
