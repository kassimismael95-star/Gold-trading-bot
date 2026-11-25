"""Verified Flutterwave v3 refund initiation and refund accounting."""
from decimal import Decimal, InvalidOperation
from datetime import datetime,timezone
import requests
from flask import current_app
from ..extensions import db
from ..models import Payment, PaymentRefund

TERMINAL_SUCCESS = {"SUCCESS", "COMPLETED", "REFUNDED"}
ACTIVE_REFUND = {"REQUESTED", "PENDING", "PROCESSING", "PENDING_REVIEW", "SUCCESS", "COMPLETED", "REFUNDED"}

def initiate_provider_refund(payment_id, amount, currency, comments="Customer refund"):
    payment = Payment.query.filter_by(id=payment_id).with_for_update().first()
    try: amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError): raise ValueError("valid_refund_amount_required")
    currency = str(currency).upper()
    if not payment or payment.status != "SUCCESS" or not payment.provider_id:
        raise ValueError("verified_successful_payment_required")
    try: rounded=amount.quantize(Decimal("0.01"))
    except InvalidOperation: raise ValueError("invalid_refund_amount_precision")
    if not amount.is_finite() or amount<=0 or amount!=rounded:
        raise ValueError("invalid_refund_amount_precision")
    if currency != payment.currency:
        raise ValueError("invalid_refund_currency")
    if not str(payment.provider_id).isdigit():
        raise ValueError("provider_transaction_id_invalid")
    refunds = PaymentRefund.query.filter_by(payment_id=payment.id).all()
    reserved = sum((Decimal(str(r.amount)) for r in refunds if r.status.upper() in ACTIVE_REFUND), Decimal("0.00"))
    if reserved + amount > Decimal(str(payment.amount)):
        raise ValueError("refund_total_exceeds_payment")
    secret = current_app.config.get("FLW_SECRET_KEY")
    if not secret: raise RuntimeError("Flutterwave secret key is not configured")
    row = PaymentRefund(payment_id=payment.id, amount=amount, currency=currency, status="REQUESTED")
    db.session.add(row); db.session.commit()
    try:
        response = requests.post(
            f"https://api.flutterwave.com/v3/transactions/{payment.provider_id}/refund",
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            json={"amount": str(amount), "comments": str(comments)[:200]}, timeout=25)
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "success" or not isinstance(body.get("data"), dict):
            raise RuntimeError("Flutterwave refund response was not successful")
        data = body["data"]
        row.provider_refund_id = str(data.get("id") or data.get("flw_ref") or "") or None
        status = str(data.get("status", "processing")).lower()
        completed_statuses={"completed-bank-transfer","completed-momo","completed-mpgs","completed-offline","completed-preauth","succeeded","success","successful","refunded"}
        row.status = "COMPLETED" if status in completed_statuses else ("FAILED" if status in {"failed","error"} else "PROCESSING")
        db.session.commit()
        if row.status=="COMPLETED":
            from .wallet_service import post_completed_refund
            post_completed_refund(row)
            apply_completed_refund_policy(payment)
            from .payment_notifications import notify_payment
            notify_payment(payment.user_id,"REFUNDED",payment.tx_ref,payment.plan_code)
        return row
    except requests.HTTPError as exc:
        # Only a definite provider 4xx rejection releases the reservation. A
        # timeout/5xx can mean the refund was accepted but the response was lost.
        status_code=getattr(getattr(exc,"response",None),"status_code",0) or 0
        row.status="FAILED" if 400<=status_code<500 else "PENDING_REVIEW"
        db.session.commit()
        raise
    except requests.RequestException:
        row.status="PENDING_REVIEW"
        db.session.commit()
        raise
    except Exception:
        row.status="PENDING_REVIEW"
        db.session.commit()
        raise


def apply_completed_refund_policy(payment):
    """Revoke the refunded subscription only after cumulative full refund."""
    from ..models import PaymentRefund,Subscription,Entitlement,TradingAccount
    from ..extensions import db
    from ..licences.service import active_entitlement
    from ..security.audit_service import record_audit
    total=PaymentRefund.query.filter_by(payment_id=payment.id,status="COMPLETED").with_entities(db.func.sum(PaymentRefund.amount)).scalar() or Decimal("0.00")
    if Decimal(str(total))<Decimal(str(payment.amount)):return False
    subscription=Subscription.query.filter_by(payment_id=payment.id).first()
    if subscription:subscription.status="REFUNDED"
    now=datetime.now(timezone.utc)
    others=Subscription.query.filter(Subscription.user_id==payment.user_id,Subscription.payment_id!=payment.id,
        Subscription.status=="ACTIVE",Subscription.expires_at>now).all()
    paid=Entitlement.query.filter_by(user_id=payment.user_id,code="BOSSMODE30D",status="ACTIVE").all()
    if others:
        latest=max(x.expires_at.replace(tzinfo=timezone.utc) if x.expires_at.tzinfo is None else x.expires_at for x in others)
        for ent in paid:ent.expires_at=latest
    else:
        for ent in paid:ent.status="REVOKED"
    if active_entitlement(payment.user_id,now) is None:
        for account in TradingAccount.query.filter_by(owner_id=payment.user_id).all():account.desired_state="STOPPED"
    record_audit("payment.refund.completed",None,"payment",payment.id,{"refunded_total":str(total)},None)
    db.session.commit();return True
