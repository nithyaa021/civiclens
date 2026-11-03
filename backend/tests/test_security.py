"""Unit tests for password hashing and JWT handling (no I/O)."""

from __future__ import annotations

import time

import pytest

from app.core.errors import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.user import Role

SECRET = "unit-test-signing-key-0123456789abcdef0123456789abcdef"
ALGO = "HS256"


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("S3cretPassword!")
    assert hashed != "S3cretPassword!"
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "S3cretPassword!")
    assert not verify_password(hashed, "S3cretPassword")


def test_verify_never_raises_on_garbage_hash() -> None:
    assert verify_password("not-a-real-hash", "anything") is False
    assert verify_password("", "anything") is False


def test_hash_uses_expected_parameters() -> None:
    # Guard against weakening the hashing policy silently.
    hashed = hash_password("AnotherOne!42")
    assert "$m=65536," in hashed  # 64 MiB memory
    assert needs_rehash(hashed) is False


def test_access_token_claims_and_type() -> None:
    token, jti = create_access_token(
        subject="665f1c2e9b0d4a2f18c3ab71",
        role=Role.CITIZEN,
        secret=SECRET,
        algorithm=ALGO,
        expires_minutes=5,
    )
    payload = decode_token(token, secret=SECRET, algorithm=ALGO, expected_type="access")
    assert payload.sub == "665f1c2e9b0d4a2f18c3ab71"
    assert payload.role == Role.CITIZEN
    assert payload.type == "access"
    assert payload.jti == jti
    assert payload.exp > time.time()


def test_refresh_token_rejected_as_access_token() -> None:
    token, _ = create_refresh_token(
        subject="u1",
        role=Role.ADMIN,
        secret=SECRET,
        algorithm=ALGO,
        expires_days=1,
    )
    with pytest.raises(UnauthorizedError) as excinfo:
        decode_token(token, secret=SECRET, algorithm=ALGO, expected_type="access")
    assert excinfo.value.code == "token_wrong_type"


def test_expired_token_rejected() -> None:
    token, _ = create_access_token(
        subject="u1",
        role=Role.CITIZEN,
        secret=SECRET,
        algorithm=ALGO,
        expires_minutes=-1,
    )
    with pytest.raises(UnauthorizedError) as excinfo:
        decode_token(token, secret=SECRET, algorithm=ALGO, expected_type="access")
    assert excinfo.value.code == "token_expired"


def test_tampered_token_rejected() -> None:
    token, _ = create_access_token(
        subject="u1",
        role=Role.CITIZEN,
        secret=SECRET,
        algorithm=ALGO,
        expires_minutes=5,
    )
    with pytest.raises(UnauthorizedError):
        decode_token(token + "x", secret=SECRET, algorithm=ALGO, expected_type="access")


def test_wrong_secret_rejected() -> None:
    token, _ = create_access_token(
        subject="u1",
        role=Role.CITIZEN,
        secret=SECRET,
        algorithm=ALGO,
        expires_minutes=5,
    )
    with pytest.raises(UnauthorizedError):
        decode_token(
            token,
            secret="a-different-long-signing-key-0123456789abcdef",
            algorithm=ALGO,
            expected_type="access",
        )
