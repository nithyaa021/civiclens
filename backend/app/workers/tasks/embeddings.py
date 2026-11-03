"""Text embedding generation task.

Algorithm: **signed feature hashing** (the "hashing trick") over word unigrams,
word bigrams and character trigrams, L2-normalised into a fixed-size vector.

This is a real, deterministic embedding - no network calls, no mock data. It is
the baseline vectoriser for complaint text; a denser semantic model can be
swapped in later without changing the task contract (same stored shape).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from celery.utils.log import get_task_logger

from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)

DEFAULT_DIMENSION = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Small English stopwords: unigrams that add noise without changing meaning.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    ]
)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _features(tokens: list[str]) -> list[str]:
    """Word unigrams (stopwords removed), word bigrams, character trigrams."""
    words = [t for t in tokens if t not in _STOPWORDS]
    feats = list(words)
    feats.extend(f"{a}_{b}" for a, b in zip(words, words[1:], strict=False))
    for word in words:
        padded = f"^{word}$"
        feats.extend(padded[i : i + 3] for i in range(len(padded) - 2))
    return feats


def embed_text(text: str, dimension: int = DEFAULT_DIMENSION) -> list[float]:
    """Return an L2-normalised feature-hash embedding for ``text``."""
    if dimension <= 0:
        raise ValueError("dimension must be positive")

    tokens = _tokenize(text)
    vector = [0.0] * dimension
    for feature in _features(tokens):
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign

    norm = sum(v * v for v in vector) ** 0.5
    if norm > 0:
        vector = [v / norm for v in vector]
    return vector


@celery_app.task(name="jobs.generate_embedding", bind=True, acks_late=True)
def generate_embedding(
    self,
    text: str,
    kind: str = "complaint",
    source_id: str | None = None,
    requested_by: str | None = None,
    dimension: int = DEFAULT_DIMENSION,
) -> dict[str, Any]:
    """Compute an embedding vector and persist it; returns a result summary."""
    from app.db.sync_mongo import get_sync_database  # worker-only import

    if not text or not text.strip():
        raise ValueError("Cannot embed empty text")

    vector = embed_text(text, dimension=dimension)
    tokens = _tokenize(text)
    document: dict[str, Any] = {
        "kind": kind,
        "source_id": source_id,
        "requested_by": requested_by,
        "dimension": dimension,
        "vector": vector,
        "token_count": len(tokens),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "created_at": datetime.now(UTC),
    }
    inserted = get_sync_database()["embeddings"].insert_one(document)

    logger.info(
        "embedding_generated task=%s embedding_id=%s tokens=%d dimension=%d",
        self.request.id,
        str(inserted.inserted_id),
        len(tokens),
        dimension,
    )
    return {
        "embedding_id": str(inserted.inserted_id),
        "dimension": dimension,
        "token_count": len(tokens),
        "kind": kind,
        "norm": round(sum(v * v for v in vector) ** 0.5, 6),
        # Full vector is not echoed back: it is persisted and fetchable from DB.
        "stored_in": "embeddings",
    }
