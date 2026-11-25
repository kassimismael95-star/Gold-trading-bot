import uuid
import requests
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from flask import current_app
from ..models import Payment, User
from ..extensions import db

PLANS={"PLAN_15D":(Decimal("25.00"),15),"PLAN_33D":(Decimal("50.00"),33),"PLAN_70D":(Decimal("100.00"),70)}

def initialize_payment(user, plan_code, currency="USD"):
    if plan_code not in PLANS: raise ValueError("invalid_plan")
    amount, days=PLANS[plan_code]
    if currency != "USD": raise ValueError("only USD is configured until merchant currency support is verified")
    secret=current_app.config.get("FLW_SECRET_KEY")
    if not secret: raise RuntimeError("Flutterwave secret key is not configured")
    tx_ref="gold-"+uuid.uuid4().hex
    row=Payment(user_id=user.id,tx_ref=tx_ref,plan_code=plan_code,amount=amount,currency=currency,status="PENDING")
    db.session.add(row); db.session.commit()
    try:
        response=requests.post("https://api.flutterwave.com/v3/payments",
          headers={"Authorization":f"Bearer {secret}","Content-Type":"application/json"},
          json={"tx_ref":tx_ref,"amount":str(amount),"currency":currency,"redirect_url":current_app.config.get("FLW_REDIRECT_URL"),
                "customer":{"email":user.email},"customizations":{"title":"Gold Scalper subscription"}},
          timeout=20)
        response.raise_for_status(); body=response.json()
        if body.get("status")!="success" or not (body.get("data") or {}).get("link"):
            raise RuntimeError("Flutterwave initialization failed")
        return row, body["data"]["link"]
    except Exception:
        row.status="INIT_FAILED"
        db.session.commit()
        raise

def verify_and_activate(tx_ref, transaction_id):
    if not tx_ref or not transaction_id: raise ValueError("transaction_reference_and_id_required")
    row=Payment.query.filter_by(tx_ref=tx_ref).with_for_update().first()
    if not row: raise ValueError("unknown_transaction")
    if row.status=="SUCCESS":
        if str(row.provider_id or "")!=str(transaction_id):
            raise ValueError("payment_already_verified_with_different_transaction")
        if row.provider_id:
            from .wallet_service import post_verified_payment
            post_verified_payment(row, str(row.provider_id))
        return row
    if row.status not in {"PENDING"}: raise ValueError("payment_not_pending")
    from .transaction_verifier import verify_transaction
    data=verify_transaction(transaction_id,row)
    row.status="SUCCESS"; row.provider_id=str(transaction_id)
    days=PLANS[row.plan_code][1]
    now=datetime.now(timezone.utc)
    from ..subscriptions.renewal_service import renewal_start
    from ..subscriptions.subscription_service import create_for_payment
    from ..licences.subscription_sync import sync_paid_entitlement
    start=renewal_start(row.user_id,now)
    subscription_expiry=start+timedelta(days=days)
    sync_paid_entitlement(row.user_id,subscription_expiry)
    create_for_payment(row,start,subscription_expiry)
    db.session.commit()
    from .wallet_service import post_verified_payment
    post_verified_payment(row, str(transaction_id))
    from .payment_notifications import notify_payment
    notify_payment(row.user_id,"SUCCESS",row.tx_ref,row.plan_code,subscription_expiry)
    return row
