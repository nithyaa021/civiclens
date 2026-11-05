"""Ward/category hotspot forecasting service (wraps :mod:`app.ai.forecast`)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi.concurrency import run_in_threadpool
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.ai.forecast import load_artifact, predict_next_days
from app.core.config import Settings
from app.core.errors import ApiError
from app.models.complaint import ComplaintCategory, ForecastPoint, ForecastResponse


async def load_daily_series(
    db: AsyncIOMotorDatabase,
    *,
    ward: int,
    category: str,
    history_days: int = 120,
) -> dict[date, int]:
    """Dense daily complaint counts for one ward+category (gaps = 0)."""
    today = datetime.now(UTC).date()
    start = today - timedelta(days=history_days - 1)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=UTC)

    pipeline = [
        {"$match": {"ward": ward, "category": category, "created_at": {"$gte": start_dt}}},
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$created_at",
                        "timezone": "UTC",
                    }
                },
                "n": {"$sum": 1},
            }
        },
    ]
    counts: dict[date, int] = {}
    async for row in db["complaints"].aggregate(pipeline):
        counts[date.fromisoformat(row["_id"])] = int(row["n"])

    day = start
    series: dict[date, int] = {}
    while day <= today:
        series[day] = counts.get(day, 0)
        day += timedelta(days=1)
    return series


async def forecast(
    db: AsyncIOMotorDatabase,
    *,
    ward: int,
    category: ComplaintCategory,
    horizon_days: int,
    settings: Settings,
) -> ForecastResponse:
    """Predict the next ``horizon_days`` for one ward and category."""
    artifact = load_artifact()
    if artifact is None:
        raise ApiError(
            503,
            "forecast_model_missing",
            "The hotspot forecaster has not been trained yet. "
            "Run `python scripts/train_models.py` to fit it.",
            details={"expected_path": settings.forecast_model_path},
        )

    series = await load_daily_series(db, ward=ward, category=category.value)
    if len(series) < settings.forecast_min_history_days:
        raise ApiError(
            409,
            "insufficient_history",
            "Not enough history for this ward/category yet "
            f"({len(series)} days, need {settings.forecast_min_history_days}).",
            details={"history_days": len(series)},
        )

    start = datetime.now(UTC).date() + timedelta(days=1)
    predictions = await run_in_threadpool(
        predict_next_days,
        artifact,
        ward=ward,
        category=category.value,
        counts=series,
        start=start,
        horizon=horizon_days,
    )
    trained_at: Any = artifact.get("trained_at")
    return ForecastResponse(
        ward=ward,
        category=category,
        horizon_days=horizon_days,
        points=[
            ForecastPoint(
                date=datetime.combine(day, datetime.min.time(), tzinfo=UTC), predicted=value
            )
            for day, value in predictions
        ],
        model=str(artifact.get("version", "xgboost-v1")),
        trained_at=trained_at if isinstance(trained_at, datetime) else None,
        holdout_mae=artifact.get("holdout_mae"),
        generated_at=datetime.now(UTC),
    )


async def known_wards(db: AsyncIOMotorDatabase) -> list[int]:
    """Ward numbers with at least one complaint (used by the forecast index)."""
    ward_numbers = [doc["ward_no"] async for doc in db["wards"].find({}, {"ward_no": 1})]
    if ward_numbers:
        return sorted(ward_numbers)
    ids = await db["complaints"].distinct("ward")
    return sorted(int(item) for item in ids if item is not None)
