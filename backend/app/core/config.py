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

    # --- Phase 2: vector search (Qdrant) ----------------------------
    # Empty url => embedded (in-process) mode at `qdrant_path`; docker-compose
    # sets QDRANT_URL to the qdrant service instead.
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_path: str = "var/qdrant"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    similar_min_score: float = Field(default=0.85, ge=-1.0, le=1.0)
    similar_geo_radius_km: float = Field(default=0.2, gt=0)
    similar_top_k: int = Field(default=8, ge=1, le=50)

    # --- Phase 2: speech-to-text & translation ----------------------
    whisper_model: str = "small"
    translation_model: str = "Xenova/nllb-200-distilled-600M"
    # Local cache for the ONNX translation files; falls back to the HF cache
    # when the directory has not been populated by scripts/warmup_models.py.
    translation_local_dir: str = "var/models/nllb"
    translation_target_lang: str = "eng_Latn"
    translation_max_tokens: int = Field(default=160, ge=8, le=512)
    language_min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    # --- Phase 2: geospatial + semantic clustering ------------------
    cluster_lookback_days: int = Field(default=60, ge=1)
    cluster_eps: float = Field(default=0.6, gt=0)
    cluster_min_samples: int = Field(default=3, ge=2)
    cluster_geo_scale_km: float = Field(default=1.0, gt=0)
    cluster_geo_weight: float = Field(default=1.0, ge=0)
    cluster_semantic_weight: float = Field(default=1.0, ge=0)

    # --- Phase 2: priority scoring ----------------------------------
    # Weights are exposed to the UI through every score breakdown; they must
    # sum to 1.0 (validated below).
    priority_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "severity": 0.30,
            "frequency": 0.15,
            "cluster_density": 0.15,
            "age_unresolved": 0.20,
            "sensitive_proximity": 0.20,
        }
    )
    priority_sensitive_radius_km: float = Field(default=1.0, gt=0)
    priority_max_age_days: float = Field(default=30.0, gt=0)
    priority_recompute_interval_minutes: int = Field(default=30, ge=1)

    # --- Phase 2: SLA & escalation ----------------------------------
    sla_targets_hours: dict[str, int] = Field(
        default_factory=lambda: {
            "roads": 72,
            "drainage": 24,
            "water_supply": 12,
            "sanitation": 24,
            "streetlight": 48,
            "waste_management": 24,
            "traffic_signal": 48,
            "noise": 24,
            "parks_trees": 96,
            "other": 72,
        }
    )
    sla_default_target_hours: int = Field(default=72, ge=1)
    # Rungs after the initial ward level: city -> command.
    escalation_ladder: list[str] = Field(default_factory=lambda: ["city", "command"])
    sla_check_interval_minutes: int = Field(default=15, ge=1)

    # --- Phase 2: resolution verification ---------------------------
    resolution_model_path: str = "var/models/resolution_comparator.joblib"
    resolution_pass_threshold: float = Field(default=0.60, ge=0.0, le=1.0)

    # --- Phase 2: hotspot forecasting -------------------------------
    forecast_model_path: str = "var/models/forecast_xgb.joblib"
    forecast_horizon_days: int = Field(default=14, ge=1, le=90)
    forecast_min_history_days: int = Field(default=28, ge=7)

    # --- Phase 2: RAG assistant -------------------------------------
    assistant_min_score: float = Field(default=0.45, ge=0.0, le=1.0)
    assistant_top_examples: int = Field(default=3, ge=1, le=10)
    assistant_max_citations: int = Field(default=20, ge=1, le=100)

    # --- Phase 2: storage paths -------------------------------------
    media_dir: str = "var/media"
    models_dir: str = "var/models"

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

    @field_validator("priority_weights", mode="after")
    @classmethod
    def _weights_sum_to_one(cls, value: dict[str, float]) -> dict[str, float]:
        required = {
            "severity",
            "frequency",
            "cluster_density",
            "age_unresolved",
            "sensitive_proximity",
        }
        missing = required - set(value)
        if missing:
            raise ValueError(f"priority_weights missing keys: {sorted(missing)}")
        if any(weight < 0 for weight in value.values()):
            raise ValueError("priority_weights must be non-negative")
        total = sum(value.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"priority_weights must sum to 1.0 (got {total:.4f})")
        return value

    @field_validator("sla_targets_hours", mode="after")
    @classmethod
    def _sla_targets_positive(cls, value: dict[str, int]) -> dict[str, int]:
        if any(hours <= 0 for hours in value.values()):
            raise ValueError("sla_targets_hours values must be positive")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cacheable/resettable in tests)."""
    return Settings()
