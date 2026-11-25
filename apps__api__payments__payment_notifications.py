"""Best-effort customer payment notifications; notification failure never rolls back payment."""
from flask import current_app
from ..models import User

def notify_payment(user_id,status,reference,plan_code=None,expires_at=None):
    sender=current_app.extensions.get("payment_notifier")
    if callable(sender):
        return sender(user_id=user_id,status=status,reference=reference,plan_code=plan_code,expires_at=expires_at)
    user=User.query.get(user_id)
    if not user:return False
    try:
        from ..auth.email_service import send_email
        subject="Gold Trading Bot payment confirmed" if status=="SUCCESS" else "Gold Trading Bot payment update"
        lines=[f"Payment status: {status}",f"Payment reference: {reference}"]
        if plan_code:lines.append(f"Subscription plan: {plan_code}")
        if expires_at:lines.append(f"Subscription expiry: {expires_at.isoformat()}")
        lines.append("You can review your subscription and account status in your dashboard.")
        send_email(user.email,subject,"\n".join(lines));return True
    except Exception:
        current_app.logger.exception("payment notification delivery failed user_id=%s reference=%s",user_id,reference)
        return False
