
"""Synchronize verified paid subscriptions with licence entitlements."""

from datetime import datetime, timezone

from ..extensions import db
from ..models import Entitlement
from .service import PAID_CODE


def sync_paid_entitlement(user_id, expires_at):
    """
    Create or update the paid entitlement after verified payment.

    The caller controls the database transaction and commits it
    together with the payment and subscription records.
    """

    if not user_id:
        raise ValueError("user_id_required")

    if not isinstance(expires_at, datetime):
        raise ValueError("valid_subscription_expiry_required")

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    entitlement = (
        Entitlement.query
        .filter_by(
            user_id=user_id,
            code=PAID_CODE,
        )
        .order_by(Entitlement.id.desc())
        .with_for_update()
        .first()
    )

    if entitlement is None:
        entitlement = Entitlement(
            user_id=user_id,
            code=PAID_CODE,
            status="ACTIVE",
            expires_at=expires_at,
        )
        db.session.add(entitlement)
    else:
        entitlement.status = "ACTIVE"
        entitlement.expires_at = expires_at

    return entitlement
