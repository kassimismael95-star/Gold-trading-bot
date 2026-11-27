
"""VIP entitlement assignment and public customer activation."""

from ..extensions import db
from ..models import Entitlement
from .service import VIP_CODES


def assign_vip(user_id, code):
    """Allow an administrator to assign a VIP code to a customer."""

    code = str(code).strip().upper()

    if code not in VIP_CODES:
        raise ValueError("invalid_vip_code")

    existing = Entitlement.query.filter(
        Entitlement.user_id == user_id,
        Entitlement.code == code,
        Entitlement.status.in_(["ACTIVE", "ASSIGNED"]),
    ).first()

    if existing:
        raise ValueError("vip_already_active_or_assigned_for_user")

    row = Entitlement(
        user_id=user_id,
        code=code,
        status="ASSIGNED",
        expires_at=None,
    )

    db.session.add(row)
    db.session.commit()

    return row


def activate_assigned_vip(user_id, code):
    """
    Activate VIP for any authenticated customer who knows
    a valid VIP code.

    Existing administrator assignments are also supported.
    VIP access has no automatic expiry.
    """

    code = str(code).strip().upper()

    if code not in VIP_CODES:
        raise ValueError("invalid_vip_code")

    # First check whether this customer already has an assignment.
    row = Entitlement.query.filter_by(
        user_id=user_id,
        code=code,
        status="ASSIGNED",
    ).first()

    if row:
        row.status = "ACTIVE"
        row.expires_at = None
        db.session.commit()
        return row

    # Prevent duplicate active VIP records.
    existing = Entitlement.query.filter_by(
        user_id=user_id,
        code=code,
        status="ACTIVE",
    ).first()

    if existing:
        return existing

    # Public activation: no administrator assignment required.
    row = Entitlement(
        user_id=user_id,
        code=code,
        status="ACTIVE",
        expires_at=None,
    )

    db.session.add(row)
    db.session.commit()

    return row
