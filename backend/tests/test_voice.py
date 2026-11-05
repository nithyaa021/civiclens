"""Voice-report upload validation and Whisper transcription."""

from __future__ import annotations

import io
import wave

import pytest
from httpx import AsyncClient

from app.workers.tasks.transcribe import get_whisper_model


def _wav_bytes(seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Mono 16-bit PCM WAV (silence) - real audio bytes Whisper can decode."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_unsupported_audio_type_is_rejected(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/voice/transcribe",
        files={"file": ("voice.txt", b"not audio", "text/plain")},
        headers=citizen_headers,
    )
    assert resp.status_code == 415


@pytest.mark.asyncio
async def test_empty_audio_is_rejected(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/voice/transcribe",
        files={"file": ("voice.wav", b"", "audio/wav")},
        headers=citizen_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_runs_whisper_and_stores_a_transcript(
    client: AsyncClient,
    citizen_headers: dict[str, str],
    citizen2_headers: dict[str, str],
) -> None:
    resp = await client.post(
        "/api/v1/voice/transcribe",
        files={"file": ("report.wav", _wav_bytes(), "audio/wav")},
        headers=citizen_headers,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["media_id"]
    assert body["status_url"].endswith(body["task_id"])

    # Eager Celery has already transcribed the clip.
    transcript = await client.get(
        f"/api/v1/voice/transcriptions/{body['media_id']}", headers=citizen_headers
    )
    assert transcript.status_code == 200, transcript.text
    payload = transcript.json()
    assert isinstance(payload["text"], str)
    assert payload["language_code"]
    assert payload["language_name"]
    assert 0.0 <= payload["language_confidence"] <= 1.0
    assert payload["duration_seconds"] >= 0.0
    assert payload["model"]

    stranger = await client.get(
        f"/api/v1/voice/transcriptions/{body['media_id']}", headers=citizen2_headers
    )
    assert stranger.status_code == 403


@pytest.mark.asyncio
async def test_unknown_transcript_is_not_found(
    client: AsyncClient, citizen_headers: dict[str, str]
) -> None:
    resp = await client.get(
        "/api/v1/voice/transcriptions/not-an-id", headers=citizen_headers
    )
    assert resp.status_code == 404


def test_whisper_supports_the_required_languages() -> None:
    model = get_whisper_model()
    supported = getattr(model, "supported_languages", None)
    assert supported is not None
    codes = {str(code).split(".")[0] for code in supported}
    for language in ("en", "hi", "kn"):
        assert language in codes, f"{language} missing from Whisper language set"
