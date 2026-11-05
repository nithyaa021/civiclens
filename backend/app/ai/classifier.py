"""Complaint category classification.

A scikit-learn pipeline (character n-gram TF-IDF + logistic regression) is
trained by ``scripts/train_models.py`` on the seeded corpus and persisted to
``settings.models_dir``.  Character n-grams work across scripts, so the same
model classifies English, Hindi (Devanagari) and Kannada texts.

When the artifact is absent (fresh checkout before training) the module
returns ``None`` honestly instead of guessing.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.complaint import ComplaintCategory, MlSuggestion

logger = get_logger("civiclens.ai.classifier")

CLASSIFIER_FILENAME = "category_classifier.joblib"
_warned_missing = False
_model: Any = None
_model_lock = threading.Lock()


def classifier_path() -> Path:
    return Path(get_settings().models_dir) / CLASSIFIER_FILENAME


def get_classifier() -> Any | None:
    """Load the trained classifier artifact; ``None`` when not yet trained."""
    global _model, _warned_missing
    if _model is not None:
        return _model
    path = classifier_path()
    if not path.exists():
        if not _warned_missing:
            logger.warning("category_classifier_missing", path=str(path))
            _warned_missing = True
        return None
    with _model_lock:
        if _model is None:
            import joblib

            _model = joblib.load(path)
            logger.info("category_classifier_loaded", path=str(path))
    return _model


def predict_category(text: str) -> MlSuggestion | None:
    """Predict the complaint category; ``None`` if the model is unavailable."""
    artifact = get_classifier()
    if artifact is None:
        return None
    model = artifact["pipeline"]
    labels: list[str] = artifact["labels"]
    probabilities = model.predict_proba([text])[0]
    order = sorted(range(len(labels)), key=lambda i: probabilities[i], reverse=True)
    top = [(ComplaintCategory(labels[i]), round(float(probabilities[i]), 4)) for i in order[:3]]
    best_label, best_prob = top[0]
    return MlSuggestion(
        predicted=best_label,
        confidence=best_prob,
        top=top,
        model_version=str(artifact["version"]),
    )


def reset_cache() -> None:
    """Drop the in-process cache (used by tests that retrain the model)."""
    global _model, _warned_missing
    with _model_lock:
        _model = None
        _warned_missing = False
