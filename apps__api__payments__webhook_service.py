"""Webhook parsing and deduplication. Routes must verify provider signature first."""
from .payment_idempotency import record_event

def accept_completed_event(payload):
    data=payload.get("data") or {}
    event_key=str(data.get("id") or data.get("tx_ref") or "")
    if not event_key: raise ValueError("webhook_event_key_missing")
    row,created=record_event("flutterwave:"+event_key,str(payload.get("event") or "unknown"),payload)
    return row,created
