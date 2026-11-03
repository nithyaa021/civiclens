"""Notification delivery task.

Every notification is persisted to the ``notifications`` collection (always a
real side effect).  When the caller asked for `email` **and** SMTP is
configured in the environment, a genuine email is sent through that server and
the outcome recorded; otherwise the result honestly reports ``email_skipped``.
"""

from __future__ import annotations

import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

from celery.utils.log import get_task_logger

from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


def _send_email(
    *,
    to_addr: str,
    subject: str,
    body: str,
    from_addr: str,
    host: str,
    port: int,
    user: str,
    password: str,
) -> None:
    """Send one plain-text email over SMTP (STARTTLS when available)."""
    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = to_addr
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.ehlo()
        try:
            smtp.starttls()
            smtp.ehlo()
        except smtplib.SMTPNotSupportedError:
            pass  # server speaks plain SMTP; still a real delivery attempt
        if user:
            smtp.login(user, password)
        smtp.send_message(message)


@celery_app.task(name="jobs.send_notification", bind=True, acks_late=True)
def send_notification(
    self,
    user_id: str,
    subject: str,
    body: str,
    channel: str = "in_app",
    requested_by: str | None = None,
) -> dict[str, Any]:
    """Deliver a notification and return an honest delivery report."""
    from bson import ObjectId
    from bson.errors import InvalidId

    from app.core.config import get_settings
    from app.db.sync_mongo import get_sync_database

    try:
        oid = ObjectId(user_id)
    except InvalidId as exc:
        raise ValueError(f"Invalid user id {user_id!r}") from exc

    db = get_sync_database()
    recipient = db["users"].find_one({"_id": oid}, {"email": 1, "full_name": 1, "status": 1})
    if recipient is None:
        raise FileNotFoundError(f"Recipient {user_id} not found")
    if recipient.get("status") != "active":
        raise ValueError(f"Recipient {user_id} is not an active account")

    email_outcome = "not_requested"
    email_error: str | None = None
    if channel == "email":
        settings = get_settings()
        if settings.smtp_enabled:
            try:
                _send_email(
                    to_addr=recipient["email"],
                    subject=subject,
                    body=body,
                    from_addr=settings.smtp_from,
                    host=settings.smtp_host,
                    port=settings.smtp_port,
                    user=settings.smtp_user,
                    password=settings.smtp_password,
                )
                email_outcome = "sent"
            except Exception as exc:  # noqa: BLE001 - delivery failures are reported, not raised
                email_outcome = "failed"
                email_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "notification_email_failed task=%s user_id=%s error=%s",
                    self.request.id,
                    user_id,
                    email_error,
                )
        else:
            email_outcome = "skipped_no_smtp"

    document = {
        "user_id": user_id,
        "subject": subject,
        "body": body,
        "channel": channel,
        "requested_by": requested_by,
        "email_status": email_outcome,
        "email_error": email_error,
        "read": False,
        "created_at": datetime.now(UTC),
    }
    inserted = db["notifications"].insert_one(document)

    logger.info(
        "notification_delivered task=%s notification_id=%s channel=%s email=%s",
        self.request.id,
        str(inserted.inserted_id),
        channel,
        email_outcome,
    )
    return {
        "notification_id": str(inserted.inserted_id),
        "user_id": user_id,
        "channel": channel,
        "delivery": "stored_in_app",
        "email": email_outcome,
        "email_error": email_error,
    }
