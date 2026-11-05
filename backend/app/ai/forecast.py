"""14-day hotspot forecasting with XGBoost.

One global regressor learns daily complaint volumes across every
(ward, category) series using calendar features, one-hot identifiers and
lagged/rolling counts.  Training uses a strict time-based split (the last
14 days are held out) and records the holdout MAE in the artifact.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger("civiclens.ai.forecast")

FORECAST_VERSION = "xgboost-v1"
CATEGORICAL = ["ward", "category", "dow", "month"]
NUMERIC = ["lag_7", "lag_14", "lag_28", "roll_7", "is_weekend", "day_index"]

_artifact: dict[str, Any] | None = None
_lock = threading.Lock()


def forecast_path() -> Path:
    return Path(get_settings().forecast_model_path)


def load_artifact() -> dict[str, Any] | None:
    """Load the trained forecast artifact; ``None`` when not trained yet."""
    global _artifact
    if _artifact is not None:
        return _artifact
    path = forecast_path()
    if not path.exists():
        return None
    with _lock:
        if _artifact is None:
            import joblib

            _artifact = joblib.load(path)
            logger.info("forecast_model_loaded", path=str(path))
    return _artifact


def reset_cache() -> None:
    """Drop the in-process artifact cache (tests retrain the model)."""
    global _artifact
    with _lock:
        _artifact = None


def _lag_features(counts: dict[date, int], day: date) -> dict[str, float]:
    def count(offset: int) -> float:
        return float(counts.get(day - timedelta(days=offset), 0))

    rolling = [count(i) for i in range(1, 8)]
    return {
        "lag_7": count(7),
        "lag_14": count(14),
        "lag_28": count(28),
        "roll_7": float(np.mean(rolling)),
        "is_weekend": 1.0 if day.weekday() >= 5 else 0.0,
        "day_index": float(day.toordinal()),
    }


def build_training_rows(
    series: dict[tuple[int, str], dict[date, int]], min_history_days: int
) -> list[dict[str, Any]]:
    """Flatten per-series daily histories into supervised rows."""
    rows: list[dict[str, Any]] = []
    for (ward, category), counts in series.items():
        if len(counts) < min_history_days:
            continue
        for day, target in counts.items():
            if (day - timedelta(days=28)) not in counts:
                continue  # need a full lag window before this sample
            rows.append(
                {
                    **_lag_features(counts, day),
                    "ward": ward,
                    "category": category,
                    "dow": day.weekday(),
                    "month": day.month,
                    "day": day,
                    "target": float(target),
                }
            )
    return rows


def _design(rows: list[dict[str, Any]], encoder: Any) -> np.ndarray:
    cats = encoder.transform([[row[name] for name in CATEGORICAL] for row in rows])
    if hasattr(cats, "toarray"):
        cats = cats.toarray()
    nums = np.asarray([[row[name] for name in NUMERIC] for row in rows], dtype=np.float64)
    return np.hstack([np.asarray(cats, dtype=np.float64), nums])


def train(
    series: dict[tuple[int, str], dict[date, int]],
    *,
    holdout_days: int = 14,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Fit the global forecaster on historical series; returns the artifact."""
    from sklearn.preprocessing import OneHotEncoder
    from xgboost import XGBRegressor

    settings = settings or get_settings()
    rows = build_training_rows(series, settings.forecast_min_history_days)
    if len(rows) < 200:
        raise ValueError(
            f"Not enough history to train the forecaster ({len(rows)} rows < 200). "
            "Seed more history first."
        )
    days = sorted({row["day"] for row in rows})
    if len(days) <= holdout_days:
        raise ValueError("History shorter than the holdout window")

    cutoff = days[-holdout_days]
    train_rows = [row for row in rows if row["day"] < cutoff]
    val_rows = [row for row in rows if row["day"] >= cutoff]
    if not train_rows or not val_rows:
        raise ValueError("Time split produced an empty side; seed more history")

    encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    encoder.fit([[row[name] for name in CATEGORICAL] for row in train_rows])

    model = XGBRegressor(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="reg:squarederror",
        tree_method="hist",
        random_state=42,
    )
    model.fit(_design(train_rows, encoder), np.asarray([row["target"] for row in train_rows]))
    val_pred = np.clip(model.predict(_design(val_rows, encoder)), 0, None)
    val_true = np.asarray([row["target"] for row in val_rows])
    holdout_mae = float(np.mean(np.abs(val_pred - val_true)))

    artifact = {
        "model": model,
        "encoder": encoder,
        "version": FORECAST_VERSION,
        "trained_at": datetime.now(UTC),
        "holdout_mae": round(holdout_mae, 4),
        "n_train": len(train_rows),
        "n_val": len(val_rows),
    }
    logger.info("forecast_trained", n_train=len(train_rows), n_val=len(val_rows), mae=holdout_mae)
    return artifact


def save_artifact(artifact: dict[str, Any], path: str | Path | None = None) -> Path:
    """Persist a trained artifact (defaults to the configured path)."""
    import joblib

    target = Path(path) if path is not None else forecast_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, target)
    return target


def predict_next_days(
    artifact: dict[str, Any],
    *,
    ward: int,
    category: str,
    counts: dict[date, int],
    start: date,
    horizon: int,
) -> list[tuple[date, int]]:
    """Recursive multi-day forecast for one ward+category series."""
    model, encoder = artifact["model"], artifact["encoder"]
    current = dict(counts)
    day = start
    predictions: list[tuple[date, int]] = []
    for _ in range(horizon):
        features = _lag_features(current, day)
        row = {
            **features,
            "ward": ward,
            "category": category,
            "dow": day.weekday(),
            "month": day.month,
        }
        value = max(0, int(round(float(model.predict(_design([row], encoder))[0]))))
        predictions.append((day, value))
        current[day] = value  # feed the prediction back into the lag window
        day += timedelta(days=1)
    return predictions
