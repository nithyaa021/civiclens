"""Centralised application settings.

Every tunable is read once from the environment (or an optional `.env` file)
and exposed as a typed attribute through :class:`Settings`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT = "development"
TEST = "test"
PRODUCTION = "production"
VALID_ENVIRONMENTS = (DEVELOPMENT, TEST, PRODUCTION)

# Secret used only when the operator has not supplied one and the app is not
# running in production.  A dedicated value keeps test/dev deterministic.
DEV_JWT_SECRET = "civiclens-development-secret-do-not-use-in-production"


class Settings(BaseSettings):
    """Typed, validated application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ------------------------------------------------
    app_name: str = "CivicLens AI"
    app_version: str = "0.1.0"
    environment: str = DEVELOPMENT
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # --- MongoDB ----------------------------------------------------
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "civiclens"

    # --- Redis ------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # --- JWT --------------------------------------------------------
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1)
    refresh_token_expire_days: int = Field(default=14, ge=1)

    # --- Rate limiting ----------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_default_limit: int = Field(default=120, ge=1)
    rate_limit_default_window_seconds: int = Field(default=60, ge=1)
    rate_limit_auth_limit: int = Field(default=10, ge=1)
    rate_limit_auth_window_seconds: int = Field(default=60, ge=1)

    # --- CORS -------------------------------------------------------
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:3000",
            "http://localhost:8080",
        ]
    )

    # --- SMTP (optional; empty host disables outbound email) --------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@civiclens.local"

    # --- Celery -----------------------------------------------------
    celery_task_always_eager: bool = False

    # --- Helpers ----------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment == PRODUCTION

    @property
    def json_logs(self) -> bool:
        """Structured JSON logs in production, human-readable elsewhere."""
        return self.environment == PRODUCTION

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host)

    # --- Validation -------------------------------------------------
    @field_validator("environment", mode="after")
    @classmethod
    def _validate_environment(cls, value: str) -> str:
        if value not in VALID_ENVIRONMENTS:
            raise ValueError(
                f"environment must be one of {', '.join(VALID_ENVIRONMENTS)} (got {value!r})"
            )
        return value

    @field_validator("jwt_secret")
    @classmethod
    def _validate_jwt_secret(cls, value: str, info) -> str:  # noqa: ANN001 - pydantic v2 signature
        # Runs after `environment` (field order), so the flag is already checked.
        environment = info.data.get("environment")
        if environment == PRODUCTION and value in ("", DEV_JWT_SECRET):
            raise ValueError(
                "JWT_SECRET must be set to a strong random value when ENVIRONMENT=production"
            )
        if environment == PRODUCTION and len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters in production")
        return value

    @field_validator("cors_origins", mode="after")
    @classmethod
    def _strip_origins(cls, value: list[str]) -> list[str]:
        return [origin.rstrip("/") for origin in value]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cacheable/resettable in tests)."""
    return Settings()
