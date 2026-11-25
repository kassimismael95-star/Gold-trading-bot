"""Database-backed idempotency helpers for webhook/payment processing."""
from hashlib import sha256
import json
from ..models import PaymentWebhookEvent
from ..extensions import db

def payload_digest(payload):
    return sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def record_event(event_key,event_type,payload):
    if not event_key: raise ValueError("event_key_required")
    existing=PaymentWebhookEvent.query.filter_by(event_key=event_key).first()
    if existing: return existing, False
    row=PaymentWebhookEvent(event_key=event_key,event_type=event_type,payload_hash=payload_digest(payload))
    db.session.add(row)
    try: db.session.commit(); return row,True
    except Exception:
        db.session.rollback()
        row=PaymentWebhookEvent.query.filter_by(event_key=event_key).first()
        if row: return row,False
        raise
