"""Image analysis task.

Computes genuine image statistics with Pillow + NumPy (no external model
downloads, nothing faked):

- basic metadata: dimensions, format, colour mode, file size, EXIF presence
- mean luminance (0-255)
- a **Laplacian-variance blur score** (industry-standard sharpness metric)
- three dominant colours from a coarse RGB histogram

The worker reads the uploaded bytes from the ``media`` collection and writes a
summary into ``job_results`` keyed by the Celery task id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import numpy as np
from celery.utils.log import get_task_logger
from PIL import Image, ImageOps

from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)

# Laplacian variance below this value on a downscaled image indicates blur.
BLUR_THRESHOLD = 45.0
MAX_WORKING_EDGE = 512  # cap resolution so huge uploads stay cheap


def _to_array(img: Image.Image) -> np.ndarray:
    """Downscale if needed and return a numpy array without colour profiles."""
    img = ImageOps.exif_transpose(img)
    if max(img.size) > MAX_WORKING_EDGE:
        img.thumbnail((MAX_WORKING_EDGE, MAX_WORKING_EDGE), Image.Resampling.LANCZOS)
    return np.asarray(img)


def laplacian_variance(gray: np.ndarray) -> float:
    """Variance of the 4-neighbour Laplacian response - higher is sharper."""
    g = gray.astype(np.float64)
    lap = np.zeros_like(g)
    lap[1:-1, 1:-1] = -4.0 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def dominant_colors(rgb: np.ndarray, top: int = 3) -> list[dict[str, Any]]:
    """Top-N colours from a 32-level-per-channel RGB histogram."""
    levels = (rgb // 32).astype(np.int64)
    codes = (levels[:, :, 0] << 10) | (levels[:, :, 1] << 5) | levels[:, :, 2]
    values, counts = np.unique(codes, return_counts=True)
    order = np.argsort(counts)[::-1][:top]
    total = float(counts.sum())
    out: list[dict[str, Any]] = []
    for idx in order:
        code = int(values[idx])
        r = ((code >> 10) & 31) * 8 + 4
        g = ((code >> 5) & 31) * 8 + 4
        b = (code & 31) * 8 + 4
        out.append(
            {
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "rgb": [int(r), int(g), int(b)],
                "share": round(float(counts[idx]) / total, 4),
            }
        )
    return out


def analyze_image_bytes(data: bytes) -> dict[str, Any]:
    """Run the full analysis pipeline on raw image bytes."""
    with Image.open(BytesIO(data)) as source:
        source.load()
        fmt = (source.format or "UNKNOWN").upper()
        mode = source.mode
        img = ImageOps.exif_transpose(source)  # honour orientation tag
        width, height = img.size
        exif = source.getexif()
        exif_tags = len(exif)
        exif_datetime = exif.get(306) if exif_tags else None  # 306 = DateTime

        rgb = img.convert("RGB")
        array = _to_array(rgb)

    brightness = float(array.mean())
    gray = np.asarray(
        rgb.convert("L").resize(
            (min(width, MAX_WORKING_EDGE), min(height, MAX_WORKING_EDGE)),
            Image.Resampling.LANCZOS,
        )
    )
    if gray.ndim != 2 or gray.size == 0:
        gray = np.asarray(rgb.convert("L"))
    blur_score = laplacian_variance(gray)

    return {
        "width": int(width),
        "height": int(height),
        "format": fmt,
        "mode": mode,
        "file_size_bytes": len(data),
        "exif_present": bool(exif_tags),
        "exif_datetime": str(exif_datetime) if exif_datetime else None,
        "brightness": round(brightness, 2),
        "blur_score": round(blur_score, 2),
        "is_blurry": bool(blur_score < BLUR_THRESHOLD),
        "dominant_colors": dominant_colors(array),
        "analysis": {
            "brightness_scale": "0 (black) - 255 (white)",
            "blur_metric": "variance of the 4-neighbour Laplacian",
            "blur_threshold": BLUR_THRESHOLD,
        },
    }


@celery_app.task(name="jobs.analyze_image", bind=True, acks_late=True)
def analyze_image(self, media_id: str, requested_by: str | None = None) -> dict[str, Any]:
    """Load a stored upload, analyse it, persist and return the summary."""
    from bson import ObjectId
    from bson.errors import InvalidId

    from app.db.sync_mongo import get_sync_database

    try:
        oid = ObjectId(media_id)
    except InvalidId as exc:
        raise ValueError(f"Invalid media id {media_id!r}") from exc

    db = get_sync_database()
    media = db["media"].find_one({"_id": oid})
    if media is None:
        raise FileNotFoundError(f"Media {media_id} not found")

    report = analyze_image_bytes(media["data"])
    document = {
        "task_id": self.request.id or "",
        "kind": "image_analysis",
        "media_id": media_id,
        "requested_by": requested_by,
        "result": report,
        "created_at": datetime.now(UTC),
    }
    db["job_results"].update_one(
        {"task_id": document["task_id"]},
        {"$set": document},
        upsert=True,
    )

    logger.info(
        "image_analyzed task=%s media_id=%s format=%s is_blurry=%s",
        self.request.id,
        media_id,
        report["format"],
        report["is_blurry"],
    )
    return report
