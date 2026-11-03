"""Synchronous MongoDB access for Celery workers.

Celery tasks run in synchronous worker processes, while the API uses the
async Motor driver.  Workers therefore get their own pooled pymongo client
(never shared with the event loop).
"""

from __future__ import annotations

from pymongo import MongoClient
from pymongo.database import Database

from app.core.config import get_settings

_client: MongoClient | None = None


def get_sync_client() -> MongoClient:
    """Return (creating on first use) the shared synchronous MongoDB client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=3000, tz_aware=True)
    return _client


def get_sync_database() -> Database:
    """Return the configured database handle for worker processes."""
    return get_sync_client()[get_settings().mongo_db]


def close_sync_client() -> None:
    """Close the pool (worker shutdown hooks)."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
