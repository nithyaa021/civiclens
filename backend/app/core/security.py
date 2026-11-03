"""Password hashing and JWT issuing/verification.

- Passwords: Argon2id (memory-hard, current OWASP recommendation).
- Tokens:    HS256 JWTs.  Access tokens are short-lived and stateless;
             refresh tokens carry a ``jti`` that the auth service tracks in
             Redis so refresh rotation can revoke the previous token.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import BaseModel, Field

from app.core.errors import UnauthorizedError
from app.models.user import Role

# Tuned for interactive logins: ~50-100ms on a typical server.
_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)

TokenKind = Literal["access", "refresh"]


class TokenPayload(BaseModel):
    """Verified claims shared by access and refresh tokens."""

    sub: str = Field(description="User id (MongoDB ObjectId string).")
    role: Role = Field(description="Role carried by the token.")
    type: TokenKind = Field(description="Discriminates access from refresh tokens.")
    jti: str = Field(description="Unique token id; refresh jtis are tracked in Redis.")
    iat: int = Field(description="Issued-at (Unix seconds).")
    exp: int = Field(description="Expiry (Unix seconds).")


# --- Passwords ----------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time verification; never raises on malformed hashes."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash used weaker parameters than the current policy."""
    return _hasher.check_needs_rehash(password_hash)


# --- Tokens -------------------------------------------------------------------
def _encode(
    *,
    subject: str,
    role: Role,
    token_type: TokenKind,
    secret: str,
    algorithm: str,
    lifetime: timedelta,
) -> tuple[str, str]:
    now = datetime.now(UTC)
    jti = uuid.uuid4().hex
    claims = {
        "sub": subject,
        "role": role.value,
        "type": token_type,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "iss": "civiclens",
    }
    token = jwt.encode(claims, key=secret, algorithm=algorithm)
    return token, jti


def create_access_token(
    *,
    subject: str,
    role: Role,
    secret: str,
    algorithm: str,
    expires_minutes: int,
) -> tuple[str, str]:
    """Issue an access token; returns ``(token, jti)``."""
    return _encode(
        subject=subject,
        role=role,
        token_type="access",
        secret=secret,
        algorithm=algorithm,
        lifetime=timedelta(minutes=expires_minutes),
    )


def create_refresh_token(
    *,
    subject: str,
    role: Role,
    secret: str,
    algorithm: str,
    expires_days: int,
) -> tuple[str, str]:
    """Issue a refresh token; returns ``(token, jti)``."""
    return _encode(
        subject=subject,
        role=role,
        token_type="refresh",
        secret=secret,
        algorithm=algorithm,
        lifetime=timedelta(days=expires_days),
    )


def decode_token(
    token: str, *, secret: str, algorithm: str, expected_type: TokenKind
) -> TokenPayload:
    """Decode and validate a JWT, enforcing the expected token type.

    Raises:
        UnauthorizedError: on expiry, tampering, malformed claims or type mismatch.
    """
    try:
        raw = jwt.decode(
            token,
            key=secret,
            algorithms=[algorithm],
            options={"require": ["exp", "iat", "sub", "jti", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token has expired.", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Token is invalid.", code="token_invalid") from exc

    try:
        payload = TokenPayload.model_validate(raw)
    except ValueError as exc:
        raise UnauthorizedError("Token claims are invalid.", code="token_invalid") from exc

    if payload.type != expected_type:
        raise UnauthorizedError(
            f"Expected a {expected_type} token but received a {payload.type} token.",
            code="token_wrong_type",
        )
    return payload
