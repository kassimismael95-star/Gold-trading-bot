
import json
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from flask import current_app

from ..models import Payment
from ..extensions import db


def load_plans():
    """Load subscription plan definitions from the project config."""
    project_root = Path(__file__).resolve().parents[3]
    config_path = project_root / "config" / "subscription_plans.json"

    with config_path.open("r", encoding="utf-8") as file:
        configured = json.load(file)

    plans = {}

    for code, details in configured.items():
        try:
            amount = Decimal(str(details["amount"]))
            currency = str(details["currency"]).upper()
            duration_days = int(details["duration_days"])
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise RuntimeError(
                f"Invalid subscription plan configuration: {code}"
            )

        if amount <= 0 or duration_days <= 0:
            raise RuntimeError(
                f"Invalid amount or duration for plan: {code}"
            )

        plans[code] = {
            "amount": amount,
            "currency": currency,
            "duration_days": duration_days,
        }

    if not plans:
        raise RuntimeError("No subscription plans are configured")

    return plans


def get_plan(plan_code):
    """Return one configured plan or raise invalid_plan."""
    plans = load_plans()

    if plan_code not in plans:
        raise ValueError("invalid_plan")

    return plans[plan_code]


def initialize_payment(user, plan_code, currency="USD"):
    plan = get_plan(plan_code)

    amount = plan["amount"]
    configured_currency = plan["currency"]
    currency = str(currency).upper()

    if currency != configured_currency:
        raise ValueError(
            "currency_does_not_match_configured_plan"
        )

    secret = current_app.config.get("FLW_SECRET_KEY")

    if not secret:
        raise RuntimeError(
            "Flutterwave secret key is not configured"
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
                "redirect_url": current_app.config.get(
                    "FLW_REDIRECT_URL"
                ),
                "customer": {
                    "email": user.email,
                },
                "customizations": {
                    "title": "Gold Scalper subscription",
                },
            },
            timeout=20,
        )

        response.raise_for_status()
        body = response.json()

        data = body.get("data") or {}
        checkout_url = data.get("link")

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

    row = (
        Payment.query
        .filter_by(tx_ref=tx_ref)
        .with_for_update()
        .first()
    )

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

    if row.status != "PENDING":
        raise ValueError("payment_not_pending")

    plan = get_plan(row.plan_code)

    if row.currency != plan["currency"]:
        raise ValueError(
            "payment_currency_does_not_match_plan"
        )

    if Decimal(str(row.amount)) != plan["amount"]:
        raise ValueError(
            "payment_amount_does_not_match_plan"
        )

    from .transaction_verifier import verify_transaction

    verify_transaction(transaction_id, row)

    row.status = "SUCCESS"
    row.provider_id = str(transaction_id)

    now = datetime.now(timezone.utc)

    from ..subscriptions.renewal_service import renewal_start
    from ..subscriptions.subscription_service import create_for_payment
    from ..licences.subscription_sync import sync_paid_entitlement

    start = renewal_start(row.user_id, now)

    subscription_expiry = start + timedelta(
        days=plan["duration_days"]
    )

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
