"""Speech-to-text task (Whisper via faster-whisper / CTranslate2).

Transcribes an uploaded audio blob, records the language Whisper detected,
and - for Hindi/Kannada speech - adds an English translation of the
transcript using the same NLLB model as the text pipeline.
"""

from __future__ import annotations

import io
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from celery.utils.log import get_task_logger

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)
log = get_logger("civiclens.workers.transcribe")

_model = None


def get_whisper_model():  # noqa: ANN202 - faster-whisper's return type
    """Load (once per process) the configured Whisper model."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        from app.core.config import get_settings

        settings = get_settings()
        _model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
        log.info("whisper_model_loaded", model=settings.whisper_model)
    return _model


@celery_app.task(name="jobs.transcribe_audio", bind=True, acks_late=True)
def transcribe_audio(self, media_id: str, requested_by: str | None = None) -> dict[str, Any]:
    """Transcribe one stored audio file and return text + language + translation."""
    from app.ai.language import language_name
    from app.ai.translation import translate_to_english
    from app.core.config import get_settings
    from app.db.sync_mongo import get_sync_database

    try:
        oid = ObjectId(media_id)
    except InvalidId as exc:
        raise ValueError(f"Invalid media id {media_id!r}") from exc

    db = get_sync_database()
    media = db["media"].find_one({"_id": oid})
    if media is None:
        raise FileNotFoundError(f"Media {media_id} not found")

    settings = get_settings()
    model = get_whisper_model()
    audio = io.BytesIO(media["data"])
    segments, info = model.transcribe(
        audio,
        beam_size=1,
        vad_filter=True,
        language=None,  # automatic detection (spec: en / hi / kn supported)
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    code = str(info.language or "en")
    confidence = float(getattr(info, "language_probability", 0.0) or 0.0)

    english_translation: str | None = None
    if (
        text
        and code not in ("en",)
        and code in ("hi", "kn", "ur", "bn", "ta", "te", "mr", "gu", "pa", "ml")
    ):
        [translated] = translate_to_english([text], [code])
        english_translation = translated or None

    result = {
        "media_id": media_id,
        "text": text,
        "language": {
            "code": code,
            "name": language_name(code),
            "confidence": round(confidence, 3),
            "method": "whisper",
        },
        "english_translation": english_translation,
        "duration_seconds": round(float(info.duration or 0.0), 2),
        "model": settings.whisper_model,
    }
    # Persist the transcript on the media record so it survives the job result.
    db["media"].update_one(
        {"_id": oid},
        {
            "$set": {
                "transcript": {
                    "text": text,
                    "language": result["language"],
                    "english_translation": english_translation,
                    "requested_by": requested_by,
                }
            }
        },
    )
    logger.info("transcription_done task=%s media_id=%s lang=%s", self.request.id, media_id, code)
    return result
