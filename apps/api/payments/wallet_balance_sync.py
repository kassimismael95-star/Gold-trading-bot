"""Fetch and record Flutterwave v3 merchant wallet balance observations."""

from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

import requests
from flask import current_app

from ..extensions import db
from ..models import WalletBalanceSnapshot, WalletReconciliation


def read_flutterwave_balances():
    secret = current_app.config.get("FLW_SECRET_KEY")

    if not secret:
        raise RuntimeError("FLW_SECRET_KEY_not_configured")

    response = requests.get(
        "https://api.flutterwave.com/v3/balances",
        headers={
            "Authorization": f"Bearer {secret}",
            "Accept": "application/json",
        },
        timeout=20,
    )

    response.raise_for_status()
    body = response.json()

    if (
        body.get("status") != "success"
        or not isinstance(body.get("data"), list)
    ):
        raise RuntimeError("flutterwave_balance_response_invalid")

    result = {}

    for item in body["data"]:
        currency = str(item.get("currency", "")).upper()

        if len(currency) != 3:
            continue

        try:
            available = Decimal(
                str(item.get("available_balance", 0))
            )
            ledger = Decimal(
                str(item.get("ledger_balance", available))
            )
        except (InvalidOperation, TypeError):
            raise RuntimeError(
                "flutterwave_balance_amount_invalid"
            )

        if not available.is_finite() or not ledger.is_finite():
            raise RuntimeError(
                "flutterwave_balance_amount_invalid"
            )

        if available < 0 or ledger < 0:
            raise RuntimeError(
                "flutterwave_balance_negative"
            )

        result[currency] = {
            "available_balance": available,
            "ledger_balance": ledger,
        }

    if not result:
        raise RuntimeError(
            "flutterwave_balance_currency_list_empty"
        )

    return result


def record_provider_balance(
    currency,
    amount,
    available_balance=None,
    provider="flutterwave",
):
    currency = str(currency).upper()
    amount = Decimal(str(amount))

    available = (
        amount
        if available_balance is None
        else Decimal(str(available_balance))
    )

    if (
        len(currency) != 3
        or not amount.is_finite()
        or not available.is_finite()
        or amount < 0
        or available < 0
    ):
        raise ValueError("invalid_provider_balance")

    # Retrieve or create the merchant ledger wallet for this currency.
    from .wallet_service import merchant_wallet

    wallet = merchant_wallet(currency)

    ledger = Decimal(str(wallet.ledger_balance or 0))

    snapshot = WalletBalanceSnapshot(
        wallet_id=wallet.id,
        currency=currency,
        provider_balance=amount,
        available_balance=available,
        ledger_balance=ledger,
        provider=provider,
        checked_at=datetime.now(timezone.utc),
    )

    db.session.add(snapshot)

    # Obtain the snapshot ID before creating its reconciliation record.
    db.session.flush()

    reconciliation = WalletReconciliation(
        snapshot_id=snapshot.id,
        currency=currency,
        provider_balance=amount,
        ledger_balance=ledger,
        difference=amount - ledger,
        status=(
            "MATCHED"
            if amount == ledger
            else "UNMATCHED"
        ),
        note=(
            "Provider ledger balance observed; settlement, fees, "
            "refunds and transfers may explain differences."
        ),
    )

    db.session.add(reconciliation)
    db.session.commit()

    return snapshot, reconciliation


def configured_balance_reader():
    """Return the verified reader unless a test/deployment adapter is injected."""
    reader = current_app.extensions.get(
        "merchant_balance_reader"
    )

    if callable(reader):
        return reader

    return read_flutterwave_balances


def sync_all_provider_balances():
    reader = configured_balance_reader()
    balances = reader()

    if not isinstance(balances, dict) or not balances:
        raise RuntimeError(
            "flutterwave_balance_currency_list_empty"
        )

    snapshots = []

    for currency, values in balances.items():
        if not isinstance(values, dict):
            raise RuntimeError(
                "flutterwave_balance_response_invalid"
            )

        snapshots.append(
            record_provider_balance(
                currency,
                values["ledger_balance"],
                values["available_balance"],
            )[0]
        )

    return snapshots
