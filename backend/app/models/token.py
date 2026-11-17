"""Token and auth endpoint payloads."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.user import Role, UserPublic

TOKEN_TYPE = "bearer"


class TokenResponse(BaseModel):
    """Returned by login and refresh; both tokens are JWTs."""

    access_token: str = Field(description="Short-lived JWT sent as a Bearer token.")
    refresh_token: str = Field(description="Long-lived JWT used to obtain a new access token.")
    token_type: str = Field(default=TOKEN_TYPE, description="Always 'bearer'.")
    expires_in: int = Field(description="Access token lifetime in seconds.", examples=[1800])
    refresh_expires_in: int = Field(
        description="Refresh token lifetime in seconds.", examples=[1209600]
    )
    user: UserPublic = Field(description="The account the tokens belong to.")


class RefreshRequest(BaseModel):
    """Payload for rotating or revoking a refresh token."""

    refresh_token: str = Field(description="Refresh token issued by /auth/login or /auth/refresh.")


class AuthMessage(BaseModel):
    """Simple acknowledgement payload."""

    message: str = Field(examples=["Refresh token revoked."])


class MeResponse(BaseModel):
    """The authenticated account."""

    user: UserPublic
    role: Role = Field(description="Denormalised role for client routing hints.")


class DemoPerspective(BaseModel):
    """A view a visitor can open in the public demo without credentials."""

    id: str = Field(
        description="Opaque id passed back to /auth/demo-session.",
        examples=["ward-12"],
    )
    label: str = Field(description="Human label for the picker.", examples=["Ward 12 · Jayanagar"])
    role: Role = Field(description="Role the demo session will hold.")
    ward: int | None = Field(
        default=None,
        description="Ward scope for ward-officer perspectives; null is city-wide.",
    )
    description: str = Field(description="One-line explanation of what this view shows.")


class DemoDirectory(BaseModel):
    """Every perspective available in the public demo."""

    enabled: bool = Field(description="False when the demo session flow is switched off.")
    default: str | None = Field(default=None, description="Perspective to open on first visit.")
    perspectives: list[DemoPerspective] = Field(
        default_factory=list, description="Ordered by role, then ward number."
    )


class DemoSessionRequest(BaseModel):
    """Pick a perspective to open.  No credentials are involved."""

    perspective: str = Field(
        min_length=1,
        max_length=32,
        description="Perspective id from GET /auth/demo, e.g. 'admin' or 'ward-12'.",
        examples=["admin"],
    )
