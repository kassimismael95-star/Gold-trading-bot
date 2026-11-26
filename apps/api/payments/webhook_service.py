
"""Parse and deduplicate verified Flutterwave webhook events.

The route must validate Flutterwave's webhook signature before calling
this module. Payment activation must still use server-side transaction
verification.
"""

from .payment_idempotency import record_event


def accept_completed_event(payload):
    if not isinstance(payload, dict):
        raise ValueError("invalid_webhook_payload")

    data = payload.get("data") or {}

    if not isinstance(data, dict):
        raise ValueError("invalid_webhook_data")

    event_type = str(payload.get("event") or "unknown").strip()

    # Flutterwave's transaction ID is the preferred stable event key.
    # tx_ref is used only when the provider event has no transaction ID.
    provider_event_id = data.get("id") or data.get("tx_ref")

    if provider_event_id is None:
        raise ValueError("webhook_event_key_missing")

    provider_event_id = str(provider_event_id).strip()

    if not provider_event_id:
        raise ValueError("webhook_event_key_missing")

    event_key = f"flutterwave:{provider_event_id}"

    event, created = record_event(
        event_key=event_key,
        event_type=event_type,
        payload=payload,
    )

    return event, created
