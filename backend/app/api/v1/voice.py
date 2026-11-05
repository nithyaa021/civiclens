"""Speech-to-text endpoints (Whisper) and transcript retrieval."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.core.deps import CurrentUserDep, DbDep, RedisDep, default_rate_limit
from app.core.errors import ApiError, ForbiddenError, NotFoundError
from app.core.uploads import ALLOWED_AUDIO_TYPES, MAX_AUDIO_BYTES, validate_upload
from app.models.user import Role
from app.models.voice import TranscriptInfo, VoiceJobQueued
from app.workers.tasks.transcribe import transcribe_audio

router = APIRouter(prefix="/voice", tags=["voice"])

OWNER_PREFIX = "job:owner:"
OWNER_TTL_SECONDS = 24 * 3600


@router.post(
    "/transcribe",
    response_model=VoiceJobQueued,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Transcribe a voice report",
    description=(
        "Uploads an audio clip (multipart) and queues Whisper transcription with "
        "automatic language detection (English, Hindi, Kannada and 97 others). "
        "The transcript, detected language and English translation (for non-English "
        "audio) are stored on the media record; poll "
        "`GET /voice/transcriptions/{media_id}` to read them."
    ),
    responses={
        202: {"description": "Clip stored and transcription queued."},
        400: {"description": "Empty upload."},
        401: {"description": "Not authenticated."},
        413: {"description": "Audio exceeds the 15 MB limit."},
        415: {"description": "Unsupported audio type."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def transcribe(
    user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
    file: Annotated[UploadFile, File(description="WAV, MP3, M4A, WebM or OGG audio.")],
) -> VoiceJobQueued:
    data = await file.read()
    content_type = validate_upload(
        content_type=file.content_type,
        data=data,
        allowed=ALLOWED_AUDIO_TYPES,
        max_bytes=MAX_AUDIO_BYTES,
        kind="audio",
    )
    from datetime import UTC, datetime

    media = await db["media"].insert_one(
        {
            "filename": file.filename or "report.audio",
            "content_type": content_type,
            "size_bytes": len(data),
            "data": data,
            "owner_id": user.id,
            "purpose": "voice_report",
            "transcript": None,
            "created_at": datetime.now(UTC),
        }
    )
    media_id = str(media.inserted_id)
    async_result = transcribe_audio.delay(media_id=media_id, requested_by=user.id)
    await redis.set(f"{OWNER_PREFIX}{async_result.id}", user.id, ex=OWNER_TTL_SECONDS)
    return VoiceJobQueued(
        media_id=media_id,
        task_id=async_result.id,
        status_url=f"/api/v1/jobs/{async_result.id}",
    )


@router.get(
    "/transcriptions/{media_id}",
    response_model=TranscriptInfo,
    status_code=status.HTTP_200_OK,
    summary="Read a stored transcript",
    description=(
        "Returns the transcript once Whisper finished. Only the uploader, staff and "
        "admins may read it."
    ),
    responses={
        200: {"description": "Transcript stored on the media record."},
        401: {"description": "Not authenticated."},
        403: {"description": "Not your upload."},
        404: {"description": "Unknown media id or transcription not finished."},
    },
)
async def get_transcript(media_id: str, user: CurrentUserDep, db: DbDep) -> TranscriptInfo:
    from bson import ObjectId

    if not ObjectId.is_valid(media_id):
        raise NotFoundError("Media", media_id)
    doc = await db["media"].find_one({"_id": ObjectId(media_id), "purpose": "voice_report"})
    if doc is None:
        raise NotFoundError("Media", media_id)
    if user.role not in (Role.ADMIN, Role.WARD_OFFICER) and doc.get("owner_id") != user.id:
        raise ForbiddenError("This recording belongs to another user.")
    transcript = doc.get("transcript")
    if not transcript:
        raise ApiError(
            404,
            "transcription_pending",
            "Transcription has not completed for this recording yet.",
            details={"media_id": media_id},
        )
    language = transcript.get("language") or {}
    return TranscriptInfo(
        media_id=media_id,
        text=transcript.get("text", ""),
        language_code=language.get("code", "en"),
        language_name=language.get("name", "English"),
        language_confidence=float(language.get("confidence", 0.0)),
        english_translation=transcript.get("english_translation"),
        duration_seconds=float(transcript.get("duration_seconds", 0.0)),
        model=transcript.get("model", "whisper"),
    )
