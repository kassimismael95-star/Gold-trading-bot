
"""Flutterwave checkout, verification and subscription activation.

The frontend never supplies an authoritative price. Prices are calculated
from the configured USD plan and a server-fetched exchange rate.
Flutterwave secret keys are read only from backend configuration.
"""

import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app

from ..models import Payment, User
from ..extensions import db


PLANS = {
    "PLAN_15D": (Decimal("25.00"), 15),
    "PLAN_33D": (Decimal("50.00"), 33),
    "PLAN_70D": (Decimal("100.00"), 70),
}

SUPPORTED_CURRENCIES = {
    "USD",
    "UGX",
    "KES",
    "TZS",
    "RWF",
    "NGN",
}

# These currencies are normally charged in whole units.
WHOLE_UNIT_CURRENCIES = {
    "UGX",
    "KES",
    "TZS",
    "RWF",
    "NGN",
}

EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/USD"
FLUTTERWAVE_CHECKOUT_URL = "https://api.flutterwave.com/v3/payments"


def _get_exchange_rate(currency):
    """Return the current USD-to-currency exchange rate."""

    currency = str(currency or "").strip().upper()

    if currency == "USD":
        return Decimal("1")

    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError("unsupported_currency")

    try:
        response = requests.get(
            EXCHANGE_RATE_URL,
            timeout=(5, 15),
        )
        response.raise_for_status()
        payload = response.json()

    except requests.RequestException as exc:
        current_app.logger.warning(
            "Exchange rate request failed for %s",
            currency,
        )
        raise RuntimeError(
            "exchange_rate_service_unavailable"
        ) from exc

    if payload.get("result") != "success":
        raise RuntimeError("exchange_rate_service_failed")

    rates = payload.get("rates") or {}
    raw_rate = rates.get(currency)

    try:
        rate = Decimal(str(raw_rate))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError("invalid_exchange_rate") from exc

    if not rate.is_finite() or rate <= 0:
        raise RuntimeError("invalid_exchange_rate")

    return rate


def _calculate_plan_amount(plan_code, currency):
    """Calculate the payment amount using server-side plan pricing."""

    if plan_code not in PLANS:
        raise ValueError("invalid_plan")

    currency = str(currency or "USD").strip().upper()

    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError("unsupported_currency")

    base_usd, plan_days = PLANS[plan_code]
    exchange_rate = _get_exchange_rate(currency)

    amount = base_usd * exchange_rate

    if currency in WHOLE_UNIT_CURRENCIES:
        amount = amount.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    else:
        amount = amount.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    if not amount.is_finite() or amount <= 0:
        raise ValueError("invalid_calculated_amount")

    return amount, plan_days, currency


def initialize_payment(user, plan_code, currency="USD"):
    """Create a pending payment and return its hosted checkout URL."""

    if user is None or not getattr(user, "id", None):
        raise ValueError("authenticated_user_required")

    amount, plan_days, currency = _calculate_plan_amount(
        plan_code,
        currency,
    )

    secret = current_app.config.get("FLW_SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "Flutterwave secret key is not configured"
        )

    redirect_url = current_app.config.get("FLW_REDIRECT_URL")
    if not redirect_url:
        raise RuntimeError(
            "Flutterwave redirect URL is not configured"
        )

    if not str(redirect_url).startswith("https://"):
        raise RuntimeError(
            "Flutterwave redirect URL must use HTTPS"
        )

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

    checkout_payload = {
        "tx_ref": tx_ref,
        "amount": str(amount),
        "currency": currency,
        "redirect_url": redirect_url,
        "customer": {
            "email": user.email,
        },
        "customizations": {
            "title": "Gold Mobile EA",
            "description": f"{plan_days}-day bot subscription",
        },
    }

    try:
        response = requests.post(
            FLUTTERWAVE_CHECKOUT_URL,
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
            },
            json=checkout_payload,
            timeout=(5, 20),
        )

        response.raise_for_status()
        body = response.json()

        checkout_url = (body.get("data") or {}).get("link")

        if body.get("status") != "success" or not checkout_url:
            raise RuntimeError(
                "Flutterwave checkout initialization failed"
            )

        return payment, checkout_url

    except Exception:
        payment.status = "INIT_FAILED"
        db.session.commit()
        raise


def verify_and_activate(tx_ref, transaction_id):
    """Verify a Flutterwave transaction and activate its subscription.

    A browser redirect or frontend success message is not proof of payment.
    Activation happens only after the provider transaction is verified.
    """

    if not tx_ref or not transaction_id:
        raise ValueError(
            "transaction_reference_and_id_required"
        )

    tx_ref = str(tx_ref).strip()
    transaction_id = str(transaction_id).strip()

    if not transaction_id.isdigit():
        raise ValueError("invalid_provider_transaction_id")

    payment = (
        Payment.query
        .filter_by(tx_ref=tx_ref)
        .with_for_update()
        .first()
    )

    if payment is None:
        raise ValueError("unknown_transaction")

    # Idempotent handling for an already verified payment.
    if payment.status == "SUCCESS":
        if str(payment.provider_id or "") != transaction_id:
            raise ValueError(
                "payment_already_verified_with_different_transaction"
            )

        if payment.provider_id:
            from .wallet_service import post_verified_payment

            post_verified_payment(
                payment,
                str(payment.provider_id),
            )

        return payment

    if payment.status != "PENDING":
        raise ValueError("payment_not_pending")

    from .transaction_verifier import verify_transaction

    verified_data = verify_transaction(
        transaction_id,
        payment,
    )

    if not isinstance(verified_data, dict):
        raise ValueError("invalid_provider_verification_response")

    payment.status = "SUCCESS"
    payment.provider_id = transaction_id

    plan = PLANS.get(payment.plan_code)
    if plan is None:
        raise ValueError("invalid_payment_plan")

    plan_days = plan[1]
    now = datetime.now(timezone.utc)

    from ..subscriptions.renewal_service import renewal_start
    from ..subscriptions.subscription_service import create_for_payment
    from ..licences.subscription_sync import sync_paid_entitlement

    subscription_start = renewal_start(
        payment.user_id,
        now,
    )

    subscription_expiry = subscription_start + timedelta(
        days=plan_days
    )

    sync_paid_entitlement(
        payment.user_id,
        subscription_expiry,
    )

    create_for_payment(
        payment,
        subscription_start,
        subscription_expiry,
    )

    db.session.commit()

    from .wallet_service import post_verified_payment

    post_verified_payment(
        payment,
        transaction_id,
    )

    from .payment_notifications import notify_payment

    notify_payment(
        payment.user_id,
        "SUCCESS",
        payment.tx_ref,
        payment.plan_code,
        subscription_expiry,
    )

    return payment
