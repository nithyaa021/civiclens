"""Authentication endpoints: registration, login, token rotation, logout."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import (
    CurrentUserDep,
    DbDep,
    RedisDep,
    SettingsDep,
    auth_rate_limit,
)
from app.models.token import (
    AuthMessage,
    DemoDirectory,
    DemoSessionRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from app.models.user import UserPublic, UserRegister
from app.services import auth as auth_service
from app.services import demo as demo_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Register a citizen account",
    description=(
        "Creates a new **citizen** account. Ward-officer and admin accounts are "
        "provisioned by administrators through `POST /users`. Registration is "
        "rate limited per client."
    ),
    responses={
        201: {"description": "Account created."},
        409: {"description": "Email already registered."},
        422: {"description": "Validation failed (weak password, bad email)."},
        429: {"description": "Rate limit exceeded."},
    },
    dependencies=[Depends(auth_rate_limit)],
)
async def register(payload: UserRegister, db: DbDep) -> UserPublic:
    return await auth_service.register_user(db, payload)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange credentials for tokens",
    description=(
        "Returns a short-lived **access token** (send as "
        "`Authorization: Bearer <token>`) and a single-use **refresh token**. "
        "Refresh tokens are rotated at `POST /auth/refresh`, which invalidates "
        "the previous one."
    ),
    responses={
        200: {"description": "Token pair issued."},
        401: {"description": "Invalid credentials or deactivated account."},
        429: {"description": "Rate limit exceeded."},
    },
    dependencies=[Depends(auth_rate_limit)],
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> TokenResponse:
    user = await auth_service.authenticate(db, form.username, form.password)
    return await auth_service.issue_tokens(db, redis, settings, user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate the refresh token",
    description=(
        "Consumes the presented refresh token and returns a **new** token pair. "
        "The old refresh token is revoked immediately, so replaying it returns "
        "`401 refresh_revoked`."
    ),
    responses={
        200: {"description": "New token pair issued."},
        401: {"description": "Expired, invalid or already-rotated refresh token."},
        429: {"description": "Rate limit exceeded."},
    },
    dependencies=[Depends(auth_rate_limit)],
)
async def refresh(
    payload: RefreshRequest,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> TokenResponse:
    return await auth_service.refresh_tokens(db, redis, settings, payload.refresh_token)


@router.post(
    "/logout",
    response_model=AuthMessage,
    status_code=status.HTTP_200_OK,
    summary="Revoke a refresh token",
    description=(
        "Blacklists the presented refresh token so it can no longer be rotated. "
        "Safe to call more than once; an unknown token still returns `200`."
    ),
    responses={
        200: {"description": "Token revoked."},
        401: {"description": "Token expired or malformed."},
    },
    dependencies=[Depends(auth_rate_limit)],
)
async def logout(
    payload: RefreshRequest,
    redis: RedisDep,
    settings: SettingsDep,
) -> AuthMessage:
    await auth_service.logout(redis, payload.refresh_token, settings)
    return AuthMessage(message="Refresh token revoked.")


@router.get(
    "/me",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    summary="Current authenticated account",
    description="Returns the account behind the presented access token.",
    responses={
        200: {"description": "Account details."},
        401: {"description": "Missing, expired or invalid access token."},
    },
)
async def me(user: CurrentUserDep) -> MeResponse:
    return MeResponse(user=user, role=user.role)


@router.get(
    "/demo",
    response_model=DemoDirectory,
    status_code=status.HTTP_200_OK,
    summary="Perspectives available in the public demo",
    description=(
        "Anonymous. Lists the seeded synthetic accounts a visitor can open the "
        "console as, so the UI can offer a view picker instead of a login form. "
        "Returns `enabled: false` when `DEMO_MODE` is off."
    ),
    responses={200: {"description": "Demo directory (possibly disabled)."}},
)
async def demo_directory(db: DbDep, settings: SettingsDep) -> DemoDirectory:
    return await demo_service.directory(db, enabled=settings.demo_mode)


@router.post(
    "/demo-session",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Open a demo session",
    description=(
        "Anonymous. Issues a normal short-lived token pair for one of the "
        "**seeded synthetic** demo accounts, so every role guard and ward scope "
        "continues to apply. Never issues tokens for real deployments' users. "
        "Rate limited on the stricter auth bucket."
    ),
    responses={
        200: {"description": "Demo token pair issued."},
        404: {"description": "Unknown perspective, or the demo is disabled."},
        429: {"description": "Rate limit exceeded."},
    },
    dependencies=[Depends(auth_rate_limit)],
)
async def demo_session(
    payload: DemoSessionRequest,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> TokenResponse:
    demo_service.assert_enabled(settings)
    doc = await demo_service.resolve(db, payload.perspective)
    user = auth_service.serialize_doc(doc)
    return await auth_service.issue_tokens(db, redis, settings, user)
