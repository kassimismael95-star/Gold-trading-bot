
"""Database-backed idempotency helpers for payment webhook processing."""

from hashlib import sha256
import json

from sqlalchemy.exc import IntegrityError

from ..models import PaymentWebhookEvent
from ..extensions import db


def payload_digest(payload):
    """Create a stable SHA-256 digest of a webhook payload."""
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )

    return sha256(serialized.encode("utf-8")).hexdigest()


def record_event(event_key, event_type, payload):
    """
    Store a webhook event once.

    Returns:
        (event_record, created)

    `created` is True only when this call created the event.
    Duplicate provider deliveries return the existing record.
    """
    event_key = str(event_key or "").strip()
    event_type = str(event_type or "unknown").strip()

    if not event_key:
        raise ValueError("event_key_required")

    if len(event_key) > 160:
        raise ValueError("event_key_too_long")

    if not event_type:
        event_type = "unknown"

    if len(event_type) > 80:
        event_type = event_type[:80]

    if not isinstance(payload, dict):
        raise ValueError("webhook_payload_must_be_object")

    digest = payload_digest(payload)

    existing = PaymentWebhookEvent.query.filter_by(
        event_key=event_key
    ).first()

    if existing:
        return existing, False

    event = PaymentWebhookEvent(
        event_key=event_key,
        event_type=event_type,
        payload_hash=digest,
        processed=False,
    )

    db.session.add(event)

    try:
        db.session.commit()
        return event, True

    except IntegrityError:
        # Another request may have inserted this event concurrently.
        db.session.rollback()

        existing = PaymentWebhookEvent.query.filter_by(
            event_key=event_key
        ).first()

        if existing:
            return existing, False

        raise

    except Exception:
        db.session.rollback()
        raise
