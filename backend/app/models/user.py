"""Domain models for users, roles and auth payloads."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class Role(StrEnum):
    """Role-based access control roles."""

    CITIZEN = "citizen"
    WARD_OFFICER = "ward_officer"
    ADMIN = "admin"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class UserBase(BaseModel):
    """Shared user fields."""

    email: EmailStr = Field(
        examples=["ananya.rao@example.com"],
        description="Unique login identifier (case-insensitive).",
    )
    full_name: str = Field(
        min_length=2,
        max_length=120,
        examples=["Ananya Rao"],
        description="Display name of the account holder.",
    )


class UserRegister(UserBase):
    """Payload for citizen self-registration."""

    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        description="Plain-text password; stored as an Argon2id hash.",
        examples=["Str0ngPass!2026"],
    )

    @field_validator("password")
    @classmethod
    def _password_not_numeric(cls, value: str) -> str:
        if value.isdigit():
            raise ValueError("Password cannot be only digits")
        return value


class UserCreate(UserBase):
    """Payload used by admins to provision ward officers and admins."""

    # Validate defaults too, so the `ward` rule below runs even when the
    # client omits the field entirely (loc points at `ward`, not the model).
    model_config = ConfigDict(validate_default=True)

    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        examples=["Str0ngPass!2026"],
    )
    role: Role = Field(
        default=Role.WARD_OFFICER,
        description="Role to assign. Only admins may call this endpoint.",
        examples=[Role.WARD_OFFICER],
    )
    ward: int | None = Field(
        default=None,
        ge=1,
        le=999,
        description="Ward number; required for ward officers.",
        examples=[12],
    )

    @field_validator("ward")
    @classmethod
    def _ward_required_for_officers(cls, value: int | None, info) -> int | None:  # noqa: ANN001
        if info.data.get("role") == Role.WARD_OFFICER and value is None:
            raise ValueError("ward is required for ward_officer accounts")
        return value


class UserPublic(BaseModel):
    """User representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Stable user identifier.", examples=["665f1c2e9b0d4a2f18c3ab71"])
    email: EmailStr = Field(examples=["ananya.rao@example.com"])
    full_name: str = Field(examples=["Ananya Rao"])
    role: Role = Field(examples=[Role.CITIZEN])
    ward: int | None = Field(
        default=None, examples=[12], description="Ward number (officers only)."
    )
    status: UserStatus = Field(examples=[UserStatus.ACTIVE])
    created_at: datetime = Field(description="Account creation timestamp (UTC).")


class OfficerRef(BaseModel):
    """Minimal officer card for assignment pickers (staff-readable)."""

    id: str
    full_name: str
    ward: int | None


class UserUpdateRole(BaseModel):
    """Admin payload for changing an account's role."""

    role: Role = Field(description="New role to assign.", examples=[Role.WARD_OFFICER])


class UserUpdateStatus(BaseModel):
    """Admin payload for activating/deactivating an account."""

    status: UserStatus = Field(description="New status.", examples=[UserStatus.INACTIVE])
