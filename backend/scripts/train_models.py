"""Train every Phase-2 model on the labeled benchmark corpus.

    python scripts/train_models.py

Artifacts written under ``settings.models_dir`` (``var/models``):

* ``category_classifier.joblib``     - char n-gram TF-IDF + logistic regression
* ``resolution_comparator.joblib``   - CLIP/SSIM/defect features + logistic regression
* ``forecast_xgb.joblib``            - global XGBoost daily-volume forecaster

Training is deterministic (fixed seeds).  The forecaster is trained on data
already in MongoDB, so run ``scripts/seed_dataset.py`` first.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.ai.forecast import FORECAST_VERSION, save_artifact  # noqa: E402
from app.ai.forecast import train as train_forecast  # noqa: E402
from app.ai.resolution import FEATURE_NAMES, extract_features  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.data.corpus import (  # noqa: E402
    directory_fingerprint,
    generate_resolution_pairs,
    split_text_samples,
)
from app.db.sync_mongo import get_sync_database  # noqa: E402


def train_classifier():
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    settings = get_settings()
    train_samples, holdout_samples = split_text_samples()
    pipeline = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(2, 5),
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
            (
                "clf",
                LogisticRegression(
                    max_iter=3000,
                    C=4.0,
                    class_weight="balanced",
                    random_state=42,
                ),
            ),
        ]
    )
    pipeline.fit(
        [sample.text for sample in train_samples],
        [sample.category.value for sample in train_samples],
    )
    labels = sorted(pipeline.classes_.tolist())
    artifact = {
        "pipeline": pipeline,
        "labels": labels,
        "version": "char-tfidf-logreg-v1",
        "trained_at": datetime.now(UTC),
        "corpus": directory_fingerprint(),
        "n_train": len(train_samples),
        "n_holdout": len(holdout_samples),
    }
    target = Path(settings.models_dir) / "category_classifier.joblib"
    target.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, target)
    print(
        f"[1/3] category classifier: {len(train_samples)} train / "
        f"{len(holdout_samples)} holdout, {len(labels)} labels -> {target}"
    )
    return artifact


def train_resolution_comparator():
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    settings = get_settings()
    pairs = generate_resolution_pairs(count=160, seed=21)
    features = []
    labels = []
    for before, after, label, _pair_id in pairs:
        extracted = extract_features(before, after)
        features.append([extracted[name] for name in FEATURE_NAMES])
        labels.append(label)

    model = Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "clf",
                LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42),
            ),
        ]
    )
    model.fit(np.asarray(features, dtype=np.float64), np.asarray(labels))
    accuracy = float(model.score(np.asarray(features), np.asarray(labels)))
    artifact = {
        "model": model,
        "feature_names": FEATURE_NAMES,
        "version": "clip-ssim-logreg-v1",
        "trained_at": datetime.now(UTC),
        "n_train": len(pairs),
        "train_accuracy": round(accuracy, 4),
    }
    target = Path(settings.resolution_model_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, target)
    print(
        f"[2/3] resolution comparator: {len(pairs)} pairs, "
        f"training accuracy {accuracy:.3f} -> {target}"
    )
    return artifact


def load_dense_series(days: int = 120) -> dict[tuple[int, str], dict[date, int]]:
    """Build dense daily series per (ward, category) from MongoDB history."""
    db = get_sync_database()
    docs = list(
        db["complaints"].find(
            {"ward": {"$ne": None}},
            {"ward": 1, "category": 1, "created_at": 1},
        )
    )
    if not docs:
        raise SystemExit(
            "No complaints in MongoDB. Run `python scripts/seed_dataset.py` first."
        )
    latest = max(doc["created_at"] for doc in docs).date()
    start = latest - timedelta(days=days - 1)

    raw: dict[tuple[int, str], dict[date, int]] = {}
    for doc in docs:
        day = doc["created_at"].date()
        if day < start:
            continue
        key = (int(doc["ward"]), str(doc["category"]))
        raw.setdefault(key, {})
        raw[key][day] = raw[key].get(day, 0) + 1

    series: dict[tuple[int, str], dict[date, int]] = {}
    for key, counts in raw.items():
        dense: dict[date, int] = {}
        day = start
        while day <= latest:
            dense[day] = counts.get(day, 0)
            day += timedelta(days=1)
        series[key] = dense
    return series


def main() -> int:
    settings = get_settings()
    Path(settings.models_dir).mkdir(parents=True, exist_ok=True)

    train_classifier()
    train_resolution_comparator()

    series = load_dense_series(days=120)
    artifact = train_forecast(series, holdout_days=settings.forecast_horizon_days)
    artifact["version"] = FORECAST_VERSION
    target = save_artifact(artifact, settings.forecast_model_path)
    print(
        f"[3/3] hotspot forecaster: {len(series)} series, "
        f"{artifact['n_train']} train rows, {artifact['n_val']} holdout rows, "
        f"holdout MAE {artifact['holdout_mae']:.3f} -> {target}"
    )
    print("\nAll models trained. Run `python scripts/evaluate.py` for the results table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
