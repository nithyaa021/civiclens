"""Voice transcription payloads."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VoiceJobQueued(BaseModel):
    """Accepted voice upload with polling handles."""

    media_id: str = Field(description="Stored audio record id.")
    task_id: str = Field(description="Celery transcription task id.")
    status_url: str = Field(description="Job status endpoint for the task.")


class TranscriptInfo(BaseModel):
    """Persisted transcript of a voice report."""

    media_id: str
    text: str = Field(description="Original-language transcript.")
    language_code: str = Field(description="Detected language code from Whisper.")
    language_name: str = Field(examples=["Hindi"])
    language_confidence: float = Field(ge=0.0, le=1.0)
    english_translation: str | None = Field(
        default=None, description="English translation (None when the audio is English)."
    )
    duration_seconds: float = Field(ge=0.0)
    model: str = Field(examples=["small"])
