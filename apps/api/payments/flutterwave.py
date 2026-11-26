
import uuid
import requests
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone
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

WHOLE_UNIT_CURRENCIES = {
    "UGX",
    "KES",
    "TZS",
    "RWF",
    "NGN",
}

EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/USD"


def calculate_plan_amount(plan_code, currency="USD"):
    """Calculate the amount from the configured USD plan on the backend."""

    if plan_code not in PLANS:
        raise ValueError("invalid_plan")

    currency = str(currency or "USD").strip().upper()

    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError("unsupported_currency")

    base_usd, days = PLANS[plan_code]

    if currency == "USD":
        rate = Decimal("1")
    else:
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

        raw_rate = (payload.get("rates") or {}).get(currency)

        try:
            rate = Decimal(str(raw_rate))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError("invalid_exchange_rate") from exc

        if not rate.is_finite() or rate <= 0:
            raise RuntimeError("invalid_exchange_rate")

    amount = base_usd * rate

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

    return amount, days, currency


def initialize_payment(user, plan_code, currency="USD"):
    """Create a pending payment and return Flutterwave checkout URL."""

    if user is None or not getattr(user, "id", None):
        raise ValueError("authenticated_user_required")

    amount, days, currency = calculate_plan_amount(
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

    row = Payment(
        user_id=user.id,
        tx_ref=tx_ref,
        plan_code=plan_code,
        amount=amount,
        currency=currency,
        status="PENDING",
    )

    db.session.add(row)
    db.session.commit()

    try:
        response = requests.post(
            "https://api.flutterwave.com/v3/payments",
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
            },
            json={
                "tx_ref": tx_ref,
                "amount": str(amount),
                "currency": currency,
                "redirect_url": redirect_url,
                "customer": {
                    "email": user.email,
                },
                "customizations": {
                    "title": "Gold Scalper subscription",
                    "description": f"{days}-day bot subscription",
                },
            },
            timeout=(5, 20),
        )

        response.raise_for_status()
        body = response.json()

        checkout_url = (body.get("data") or {}).get("link")

        if body.get("status") != "success" or not checkout_url:
            raise RuntimeError(
                "Flutterwave initialization failed"
            )

        return row, checkout_url

    except Exception:
        row.status = "INIT_FAILED"
        db.session.commit()
        raise


def verify_and_activate(tx_ref, transaction_id):
    if not tx_ref or not transaction_id:
        raise ValueError(
            "transaction_reference_and_id_required"
        )

    row = Payment.query.filter_by(
        tx_ref=tx_ref
    ).with_for_update().first()

    if not row:
        raise ValueError("unknown_transaction")

    if row.status == "SUCCESS":
        if str(row.provider_id or "") != str(transaction_id):
            raise ValueError(
                "payment_already_verified_with_different_transaction"
            )

        if row.provider_id:
            from .wallet_service import post_verified_payment

            post_verified_payment(
                row,
                str(row.provider_id),
            )

        return row

    if row.status not in {"PENDING"}:
        raise ValueError("payment_not_pending")

    from .transaction_verifier import verify_transaction

    data = verify_transaction(
        transaction_id,
        row,
    )

    row.status = "SUCCESS"
    row.provider_id = str(transaction_id)

    days = PLANS[row.plan_code][1]
    now = datetime.now(timezone.utc)

    from ..subscriptions.renewal_service import renewal_start
    from ..subscriptions.subscription_service import create_for_payment
    from ..licences.subscription_sync import sync_paid_entitlement

    start = renewal_start(
        row.user_id,
        now,
    )

    subscription_expiry = start + timedelta(days=days)

    sync_paid_entitlement(
        row.user_id,
        subscription_expiry,
    )

    create_for_payment(
        row,
        start,
        subscription_expiry,
    )

    db.session.commit()

    from .wallet_service import post_verified_payment

    post_verified_payment(
        row,
        str(transaction_id),
    )

    from .payment_notifications import notify_payment

    notify_payment(
        row.user_id,
        "SUCCESS",
        row.tx_ref,
        row.plan_code,
        subscription_expiry,
    )

    return row
