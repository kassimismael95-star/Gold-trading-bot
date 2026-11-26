
"""Database-backed idempotency helpers for payment webhooks."""

from hashlib import sha256
import json

from sqlalchemy.exc import IntegrityError

from ..models import PaymentWebhookEvent
from ..extensions import db


def payload_digest(payload):
    """Create a stable SHA-256 digest for a webhook payload."""

    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )

    return sha256(serialized.encode("utf-8")).hexdigest()


def record_event(event_key, event_type, payload):
    """Record a webhook once using its unique event key.

    Returns:
        (event_row, created)
        created is True only when this call created the database record.
    """

    event_key = str(event_key or "").strip()
    event_type = str(event_type or "unknown").strip()[:80]

    if not event_key:
        raise ValueError("event_key_required")

    if len(event_key) > 160:
        raise ValueError("event_key_too_long")

    if not isinstance(payload, dict):
        raise ValueError("webhook_payload_must_be_object")

    digest = payload_digest(payload)

    existing = PaymentWebhookEvent.query.filter_by(
        event_key=event_key
    ).first()

    if existing is not None:
        return existing, False

    row = PaymentWebhookEvent(
        event_key=event_key,
        event_type=event_type or "unknown",
        payload_hash=digest,
        processed=False,
    )

    db.session.add(row)

    try:
        db.session.commit()
        return row, True

    except IntegrityError:
        # Another webhook request may have inserted the same key
        # at nearly the same time. Roll back this transaction and
        # retrieve the winning row.
        db.session.rollback()

        existing = PaymentWebhookEvent.query.filter_by(
            event_key=event_key
        ).first()

        if existing is not None:
            return existing, False

        # The integrity error was unrelated to a duplicate event.
        raise

    except Exception:
        db.session.rollback()
        raise
