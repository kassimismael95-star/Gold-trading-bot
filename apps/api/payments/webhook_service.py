
"""Webhook parsing and deduplication.

The payment route must verify Flutterwave's webhook signature before calling
these helpers. This module does not activate payments or trust webhook status.
"""

from .payment_idempotency import record_event


def accept_completed_event(payload):
    """Store a completed-payment webhook once.

    Returns:
        (event_row, created)

    `created` is True only when this call successfully created the event row.
    Repeated delivery of the same provider event returns the existing row.
    """
    if not isinstance(payload, dict):
        raise ValueError("webhook_payload_must_be_object")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("webhook_data_must_be_object")

    event_type = str(payload.get("event") or "unknown").strip()
    transaction_id = str(data.get("id") or "").strip()
    transaction_ref = str(data.get("tx_ref") or "").strip()

    # Prefer Flutterwave's transaction ID. Use tx_ref only as a fallback.
    provider_event_id = transaction_id or transaction_ref
    if not provider_event_id:
        raise ValueError("webhook_event_key_missing")

    if len(provider_event_id) > 140:
        raise ValueError("webhook_event_key_too_long")

    event_key = f"flutterwave:{provider_event_id}"

    return record_event(
        event_key=event_key,
        event_type=event_type[:80] or "unknown",
        payload=payload,
    )
