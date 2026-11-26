
"""Server-side Flutterwave verification.

Never trust a browser redirect or client-supplied payment status.
Verify the transaction directly with Flutterwave before activation.
"""

from decimal import Decimal, InvalidOperation

import requests
from flask import current_app

from ..models import Payment, User


FLUTTERWAVE_VERIFY_URL = (
    "https://api.flutterwave.com/v3/transactions/{transaction_id}/verify"
)


def verify_transaction(transaction_id, payment=None):
    """Verify a Flutterwave transaction and optionally match it to a Payment.

    Args:
        transaction_id: Flutterwave's numeric transaction ID.
        payment: The locally stored Payment row to verify against.

    Returns:
        Flutterwave's verified transaction data.

    Raises:
        ValueError: If the transaction is invalid or does not match.
        RuntimeError: If the provider secret is not configured.
        requests.RequestException: If Flutterwave cannot be reached.
    """

    transaction_id = str(transaction_id or "").strip()

    if not transaction_id or not transaction_id.isdigit():
        raise ValueError("invalid_provider_transaction_id")

    secret = current_app.config.get("FLW_SECRET_KEY")

    if not secret:
        raise RuntimeError("flutterwave_secret_not_configured")

    url = FLUTTERWAVE_VERIFY_URL.format(
        transaction_id=transaction_id
    )

    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {secret}",
            "Accept": "application/json",
        },
        timeout=(5, 20),
    )

    response.raise_for_status()

    try:
        body = response.json()
    except ValueError as exc:
        raise ValueError("invalid_provider_response") from exc

    if not isinstance(body, dict):
        raise ValueError("invalid_provider_response")

    if body.get("status") != "success":
        raise ValueError("provider_verification_failed")

    data = body.get("data")

    if not isinstance(data, dict):
        raise ValueError("invalid_provider_transaction_data")

    if str(data.get("status", "")).lower() != "successful":
        raise ValueError("transaction_not_successful")

    # If no local payment was supplied, return the verified provider data.
    if payment is None:
        return data

    # Ensure the provider transaction is the one requested.
    if str(data.get("id", "")) != transaction_id:
        raise ValueError("provider_transaction_id_mismatch")

    # Match the transaction to the payment created by our backend.
    if str(data.get("tx_ref", "")) != str(payment.tx_ref):
        raise ValueError("payment_reference_mismatch")

    provider_currency = str(data.get("currency", "")).strip().upper()
    expected_currency = str(payment.currency or "").strip().upper()

    if not provider_currency or provider_currency != expected_currency:
        raise ValueError("payment_currency_mismatch")

    # Compare decimal values exactly; do not use floating-point arithmetic.
    try:
        verified_amount = Decimal(str(data.get("amount", "")))
        expected_amount = Decimal(str(payment.amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid_verified_amount") from exc

    if (
        not verified_amount.is_finite()
        or not expected_amount.is_finite()
        or verified_amount != expected_amount
    ):
        raise ValueError("payment_amount_mismatch")

    # Check customer email when Flutterwave supplies one.
    customer_data = data.get("customer") or {}

    if not isinstance(customer_data, dict):
        raise ValueError("invalid_provider_customer_data")

    provider_email = str(
        customer_data.get("email") or ""
    ).strip().lower()

    owner = User.query.get(payment.user_id)

    if owner is None:
        raise ValueError("payment_user_not_found")

    owner_email = str(owner.email or "").strip().lower()

    if provider_email and owner_email and provider_email != owner_email:
        raise ValueError("payment_customer_mismatch")

    # Prevent the same Flutterwave transaction from paying two records.
    duplicate = (
        Payment.query
        .filter(
            Payment.provider_id == transaction_id,
            Payment.id != payment.id,
        )
        .first()
    )

    if duplicate:
        raise ValueError("transaction_already_applied")

    return data
