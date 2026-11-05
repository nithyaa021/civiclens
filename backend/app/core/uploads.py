"""Shared upload validation for images and audio files."""

from __future__ import annotations

from app.core.errors import ApiError

# Image uploads are capped; larger files are rejected with 413.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp"}
)

# Audio uploads (voice reports) are capped separately.
MAX_AUDIO_BYTES = 15 * 1024 * 1024
ALLOWED_AUDIO_TYPES = frozenset(
    {
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp4",
        "audio/webm",
        "audio/ogg",
        "audio/x-m4a",
    }
)


def validate_upload(
    *,
    content_type: str | None,
    data: bytes,
    allowed: frozenset[str],
    max_bytes: int,
    kind: str = "image",
) -> str:
    """Validate an uploaded file; returns the normalised content type.

    Raises:
        ApiError: 415 for unsupported types, 413 for oversized files,
            400 for empty files.
    """
    normalised = (content_type or "").lower()
    if normalised not in allowed:
        raise ApiError(
            415,
            "unsupported_media_type",
            f"Unsupported {kind} type {content_type or 'unknown'!r}. "
            f"Allowed: {', '.join(sorted(allowed))}.",
        )
    if len(data) > max_bytes:
        raise ApiError(
            413,
            "payload_too_large",
            f"Uploaded {kind} exceeds the {max_bytes // (1024 * 1024)} MB limit.",
            details={"size_bytes": len(data), "max_bytes": max_bytes},
        )
    if not data:
        raise ApiError(400, "empty_file", "Uploaded file is empty.")
    return normalised
