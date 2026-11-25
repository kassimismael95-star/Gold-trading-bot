"""Create payment-linked subscription history idempotently."""
from ..extensions import db
from ..models import Subscription

def create_for_payment(payment,start_at,expires_at):
    existing=Subscription.query.filter_by(payment_id=payment.id).first()
    if existing:return existing
    row=Subscription(user_id=payment.user_id,payment_id=payment.id,plan_code=payment.plan_code,
        status="ACTIVE",starts_at=start_at,expires_at=expires_at)
    db.session.add(row);return row
