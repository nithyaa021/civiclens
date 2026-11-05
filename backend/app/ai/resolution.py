"""Before/after photo comparison for resolution verification.

Two real models contribute:

1. **CLIP ViT-B/32 vision** (ONNX via fastembed) - embeds both photos and
   yields a scene-similarity score; low similarity means the "after" photo is
   not the same place, which drags confidence down through the comparator.
2. **Trained comparator** - a logistic regression over explainable image
   features (CLIP similarity, global SSIM, brightness/dark-spot/edge deltas)
   fitted by ``scripts/train_models.py`` on labelled before/after pairs and
   persisted to ``settings.resolution_model_path``.

There is no heuristic fallback: if the comparator artifact is missing the
verification fails honestly and tells the operator to run the training script.
"""

from __future__ import annotations

import io
import threading
from typing import Any

import numpy as np
from PIL import Image

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("civiclens.ai.resolution")

VISION_MODEL_NAME = "Qdrant/clip-ViT-B-32-vision"
FEATURE_NAMES = [
    "clip_sim",
    "ssim",
    "brightness_delta",
    "dark_ratio_delta",
    "edge_density_delta",
    "laplacian_var_ratio",
]

_vision_model: Any = None
_comparator: Any = None
_lock = threading.Lock()


class ResolutionModelMissing(RuntimeError):
    """Raised when the trained comparator artifact does not exist."""


def get_vision_model() -> Any:
    global _vision_model
    if _vision_model is None:
        with _lock:
            if _vision_model is None:
                from fastembed import ImageEmbedding

                _vision_model = ImageEmbedding(model_name=VISION_MODEL_NAME)
                logger.info("vision_model_loaded", model=VISION_MODEL_NAME)
    return _vision_model


def load_comparator() -> dict[str, Any] | None:
    """Load the trained comparator artifact (``None`` before training)."""
    global _comparator
    if _comparator is not None:
        return _comparator
    from pathlib import Path

    path = Path(get_settings().resolution_model_path)
    if not path.exists():
        return None
    with _lock:
        if _comparator is None:
            import joblib

            _comparator = joblib.load(path)
            logger.info("resolution_comparator_loaded", path=str(path))
    return _comparator


def reset_cache() -> None:
    """Drop cached models (tests retrain the comparator)."""
    global _vision_model, _comparator
    with _lock:
        _vision_model = None
        _comparator = None


def _to_gray(img: Image.Image, size: int = 128) -> np.ndarray:
    return np.asarray(img.convert("L").resize((size, size)), dtype=np.float64) / 255.0


def _global_ssim(a: np.ndarray, b: np.ndarray, block: int = 16) -> float:
    """Mean SSIM over non-overlapping blocks (luminance channel)."""
    c1, c2 = (0.01 * 1.0) ** 2, (0.03 * 1.0) ** 2
    scores: list[float] = []
    for y in range(0, a.shape[0], block):
        for x in range(0, a.shape[1], block):
            sa = a[y : y + block, x : x + block]
            sb = b[y : y + block, x : x + block]
            if sa.size == 0:
                continue
            mu_a, mu_b = sa.mean(), sb.mean()
            var_a, var_b = sa.var(), sb.var()
            cov = ((sa - mu_a) * (sb - mu_b)).mean()
            numerator = (2 * mu_a * mu_b + c1) * (2 * cov + c2)
            denominator = (mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2)
            scores.append(numerator / denominator)
    return float(np.mean(scores)) if scores else 0.0


def _dark_ratio(gray: np.ndarray, threshold: float = 0.25) -> float:
    return float((gray < threshold).mean())


def _edge_density(gray: np.ndarray) -> float:
    grad_y = np.abs(np.diff(gray, axis=0)).mean()
    grad_x = np.abs(np.diff(gray, axis=1)).mean()
    return float((grad_x + grad_y) / 2.0)


def _laplacian_var(gray: np.ndarray) -> float:
    lap = gray[1:-1, 1:-1] * 4 - gray[:-2, 1:-1] - gray[2:, 1:-1] - gray[1:-1, :-2] - gray[1:-1, 2:]
    return float(lap.var())


def _clip_vector(img: Image.Image) -> np.ndarray:
    model = get_vision_model()
    [vector] = list(model.embed([img.convert("RGB")]))
    return np.asarray(vector, dtype=np.float64)


def extract_features(before_bytes: bytes, after_bytes: bytes) -> dict[str, float]:
    """Compute the explainable feature vector for one before/after pair."""
    before = Image.open(io.BytesIO(before_bytes)).convert("RGB")
    after = Image.open(io.BytesIO(after_bytes)).convert("RGB")

    clip_before, clip_after = _clip_vector(before), _clip_vector(after)
    denom = float(np.linalg.norm(clip_before) * np.linalg.norm(clip_after))
    clip_sim = float(np.dot(clip_before, clip_after) / denom) if denom else 0.0

    gray_before, gray_after = _to_gray(before), _to_gray(after)
    return {
        "clip_sim": round(clip_sim, 6),
        "ssim": round(_global_ssim(gray_before, gray_after), 6),
        "brightness_delta": round(float(gray_after.mean() - gray_before.mean()), 6),
        "dark_ratio_delta": round(_dark_ratio(gray_after) - _dark_ratio(gray_before), 6),
        "edge_density_delta": round(_edge_density(gray_after) - _edge_density(gray_before), 6),
        "laplacian_var_ratio": round(
            (_laplacian_var(gray_after) + 1e-6) / (_laplacian_var(gray_before) + 1e-6), 6
        ),
    }


def verify_fix(before_bytes: bytes, after_bytes: bytes) -> tuple[float, dict[str, float], str]:
    """Return ``(confidence, features, model_version)`` for one pair.

    Raises:
        ResolutionModelMissing: when the comparator has not been trained yet.
    """
    features = extract_features(before_bytes, after_bytes)
    artifact = load_comparator()
    if artifact is None:
        raise ResolutionModelMissing(
            "Resolution comparator not trained. Run `python scripts/train_models.py` first."
        )
    model = artifact["model"]
    ordered = np.array([[features[name] for name in artifact["feature_names"]]], dtype=np.float64)
    confidence = float(model.predict_proba(ordered)[0, 1])
    return round(confidence, 4), features, str(artifact["version"])
