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
