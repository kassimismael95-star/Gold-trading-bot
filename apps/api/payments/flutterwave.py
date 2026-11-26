
"""Flutterwave checkout and verified subscription activation."""

import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app

from ..models import Payment
from ..extensions import db


# Keep these plan codes synchronized with the website's plan cards.
PLANS = {
    "PLAN_15D": (Decimal("25.00"), 15),
    "PLAN_33D": (Decimal("50.00"), 33),
    "PLAN_70D": (Decimal("100.00"), 70),
}


def initialize_payment(user, plan_code, currency="USD"):
    """Create a pending payment and obtain a provider checkout URL."""

    plan_code = str(plan_code or "").strip()
    currency = str(currency or "").strip().upper()

    if plan_code not in PLANS:
        raise ValueError("invalid_plan")

    amount, _days = PLANS[plan_code]

    if currency != "USD":
        raise ValueError(
            "only USD is configured until merchant currency support is verified"
        )

    secret = current_app.config.get("FLW_SECRET_KEY")

    if not secret:
        raise RuntimeError(
            "Flutterwave secret key is not configured"
        )

    redirect_url = current_app.config.get(
        "FLW_REDIRECT_URL"
    )

    if not redirect_url:
        raise RuntimeError(
            "Flutterwave redirect URL is not configured"
        )

    if not getattr(user, "email", None):
        raise ValueError("customer_email_required")

    tx_ref = "gold-" + uuid.uuid4().hex

    payment = Payment(
        user_id=user.id,
        tx_ref=tx_ref,
        plan_code=plan_code,
        amount=amount,
        currency=currency,
        status="PENDING",
    )

    db.session.add(payment)
    db.session.commit()

    payload = {
        "tx_ref": tx_ref,
        "amount": str(amount),
        "currency": currency,
        "redirect_url": redirect_url,
        "customer": {
            "email": user.email,
        },
        "customizations": {
            "title": "Gold Scalper subscription",
        },
    }

    try:
        response = requests.post(
            "https://api.flutterwave.com/v3/payments",
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(5, 20),
        )

        response.raise_for_status()

        body = response.json()
        data = body.get("data") or {}

        checkout_url = data.get("link")

        if (
            body.get("status") != "success"
            or not isinstance(checkout_url, str)
            or not checkout_url.startswith("https://")
        ):
            raise RuntimeError(
                "Flutterwave initialization failed"
            )

        return payment, checkout_url

    except Exception:
        payment.status = "INIT_FAILED"
        db.session.commit()
        raise


def verify_and_activate(tx_ref, transaction_id):
    """
    Verify the transaction directly with Flutterwave.

    Never activate a subscription from a browser redirect alone.
    """

    tx_ref = str(tx_ref or "").strip()
    transaction_id = str(transaction_id or "").strip()

    if not tx_ref or not transaction_id:
        raise ValueError(
            "transaction_reference_and_id_required"
        )

    if not transaction_id.isdigit():
        raise ValueError(
            "invalid_provider_transaction_id"
        )

    payment = (
        Payment.query
        .filter_by(tx_ref=tx_ref)
        .with_for_update()
        .first()
    )

    if payment is None:
        raise ValueError("unknown_transaction")

    # Idempotent handling of an already verified payment.
    if payment.status == "SUCCESS":
        if str(payment.provider_id or "") != transaction_id:
            raise ValueError(
                "payment_already_verified_with_different_transaction"
            )

        from .wallet_service import post_verified_payment

        post_verified_payment(
            payment,
            str(payment.provider_id),
        )

        return payment

    if payment.status != "PENDING":
        raise ValueError("payment_not_pending")

    # This service checks the provider's transaction ID,
    # reference, status, amount, currency, customer and duplicates.
    from .transaction_verifier import verify_transaction

    verify_transaction(transaction_id, payment)

    payment.status = "SUCCESS"
    payment.provider_id = transaction_id

    if payment.plan_code not in PLANS:
        raise ValueError("payment_has_invalid_plan")

    _amount, days = PLANS[payment.plan_code]

    now = datetime.now(timezone.utc)

    from ..subscriptions.renewal_service import renewal_start
    from ..subscriptions.subscription_service import (
        create_for_payment,
    )
    from ..licences.subscription_sync import (
        sync_paid_entitlement,
    )

    # Preserve any remaining active subscription time.
    start_at = renewal_start(payment.user_id, now)
    expires_at = start_at + timedelta(days=days)

    # Synchronize paid licence entitlement and subscription history.
    sync_paid_entitlement(
        payment.user_id,
        expires_at,
    )

    create_for_payment(
        payment,
        start_at,
        expires_at,
    )

    db.session.commit()

    # Keep the existing wallet ledger integration.
    from .wallet_service import post_verified_payment

    post_verified_payment(
        payment,
        transaction_id,
    )

    # Notify the customer after verification and activation.
    from .payment_notifications import notify_payment

    notify_payment(
        payment.user_id,
        "SUCCESS",
        payment.tx_ref,
        payment.plan_code,
        expires_at,
    )

    return payment
