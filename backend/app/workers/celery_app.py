"""Celery application instance shared by the API (enqueue) and worker (execute)."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()

# Logging must be configured before workers import task modules.
configure_logging(settings.log_level, json_logs=settings.json_logs)

celery_app = Celery(
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks.embeddings",
        "app.workers.tasks.image_analysis",
        "app.workers.tasks.notifications",
    ],
)

celery_app.conf.update(
    # --- Serialization -------------------------------------------------
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # --- Reliability ---------------------------------------------------
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    # --- Result backend ------------------------------------------------
    result_expires=24 * 3600,
    result_extended=True,
    # --- Routing -------------------------------------------------------
    task_default_queue="civiclens",
    task_routes={
        "jobs.generate_embedding": {"queue": "civiclens"},
        "jobs.analyze_image": {"queue": "civiclens"},
        "jobs.send_notification": {"queue": "civiclens"},
    },
    # --- Timeouts ------------------------------------------------------
    task_time_limit=5 * 60,
    task_soft_time_limit=4 * 60,
    # --- Test mode -----------------------------------------------------
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=False,
    # Persist eager results so AsyncResult works under tests.
    task_store_eager_result=settings.celery_task_always_eager,
)
