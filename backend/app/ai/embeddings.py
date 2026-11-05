"""Text embeddings backed by fastembed (ONNX, no PyTorch).

The model is loaded lazily on first use and shared process-wide.  All
functions here are synchronous; async callers wrap them with
``fastapi.concurrency.run_in_threadpool`` so the event loop never blocks.
"""

from __future__ import annotations

import threading
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("civiclens.ai.embeddings")

_model: Any = None
_model_lock = threading.Lock()


def get_text_model() -> Any:
    """Return (loading on first call) the shared fastembed text model."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from fastembed import TextEmbedding

                settings = get_settings()
                _model = TextEmbedding(model_name=settings.embedding_model)
                logger.info("embedding_model_loaded", model=settings.embedding_model)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts into L2-normalisable float vectors."""
    if not texts:
        return []
    model = get_text_model()
    vectors = [vector.tolist() for vector in model.embed(texts)]
    settings = get_settings()
    if len(vectors) != len(texts):
        raise RuntimeError("embedding model returned an unexpected batch size")
    if vectors and len(vectors[0]) != settings.embedding_dim:
        raise RuntimeError(
            f"embedding dim mismatch: model returned {len(vectors[0])}, "
            f"settings expect {settings.embedding_dim}"
        )
    return vectors


def embed_one(text: str) -> list[float]:
    """Embed a single text."""
    return embed_texts([text])[0]
