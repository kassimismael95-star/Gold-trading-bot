"""Server-side Flutterwave verification adapter; never trusts browser callbacks."""
from decimal import Decimal,InvalidOperation
import requests
from flask import current_app
from ..models import Payment,User

def verify_transaction(transaction_id,payment=None):
    transaction_id=str(transaction_id)
    if not transaction_id.isdigit():raise ValueError("invalid_provider_transaction_id")
    secret=current_app.config.get("FLW_SECRET_KEY")
    if not secret:raise RuntimeError("flutterwave_secret_not_configured")
    response=requests.get(f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify",
        headers={"Authorization":f"Bearer {secret}"},timeout=(5,20))
    response.raise_for_status();body=response.json()
    if body.get("status")!="success":raise ValueError("provider_verification_failed")
    data=body.get("data") or {}
    if data.get("status")!="successful":raise ValueError("transaction_not_successful")
    if payment is None:return data
    if str(data.get("id",""))!=transaction_id:raise ValueError("provider_transaction_id_mismatch")
    if str(data.get("tx_ref",""))!=payment.tx_ref:raise ValueError("payment_reference_mismatch")
    if str(data.get("currency"," ")).upper()!=payment.currency:raise ValueError("payment_currency_mismatch")
    try:amount=Decimal(str(data.get("amount","0")))
    except (InvalidOperation,TypeError,ValueError):raise ValueError("invalid_verified_amount")
    if not amount.is_finite() or amount!=Decimal(str(payment.amount)):raise ValueError("payment_amount_mismatch")
    customer=str((data.get("customer") or {}).get("email") or "").strip().lower()
    owner=User.query.get(payment.user_id)
    if customer and owner and customer!=owner.email.lower():raise ValueError("payment_customer_mismatch")
    duplicate=Payment.query.filter(Payment.provider_id==transaction_id,Payment.id!=payment.id).first()
    if duplicate:raise ValueError("transaction_already_applied")
    return data
