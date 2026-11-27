
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from ..models import Entitlement, Subscription
from ..security import current_user
from .service import (
    VIP_CODES,
    TRIAL_CODE,
    PAID_CODE,
    MAX_TRIALS,
    active_entitlement,
)

bp = Blueprint(
    "licences",
    __name__,
    url_prefix="/api/licences",
)


def _aware(value):
    if value and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _active_paid_subscription(user_id, now):
    subscriptions = (
        Subscription.query
        .filter_by(user_id=user_id, status="ACTIVE")
        .order_by(Subscription.expires_at.desc())
        .all()
    )

    for subscription in subscriptions:
        expiry = _aware(subscription.expires_at)

        if expiry and expiry > now:
            return subscription

    return None


@bp.post("/activate")
@jwt_required()
def activate():
    user = current_user()
    data = request.get_json(silent=True) or {}

    code = str(data.get("code", "")).strip().upper()
    now = datetime.now(timezone.utc)

    if not code:
        return jsonify(error="licence_code_required"), 400

    if code in VIP_CODES:
        from .activation_service import activate_vip_for_user

        try:
            row = activate_vip_for_user(user.id, code)
        except ValueError as exc:
            return jsonify(error=str(exc)), 403

        return jsonify(
            status="ACTIVE",
            active=True,
            code=row.code,
            expires_at=None,
        ), 200

    if code == TRIAL_CODE:
        from .activation_service import activate_trial_for_user

        existing = active_entitlement(user.id, now)

        if existing:
            return jsonify(
                error="an_active_entitlement_already_exists",
                active_code=existing.code,
                expires_at=(
                    existing.expires_at.isoformat()
                    if existing.expires_at else None
                ),
            ), 409

        row, error, eligible_at = activate_trial_for_user(
            user.id,
            now,
        )

        if error:
            return jsonify(
                error=error,
                eligible_at=(
                    eligible_at.isoformat()
                    if eligible_at else None
                ),
            ), 409

        return jsonify(
            status="ACTIVE",
            active=True,
            code=row.code,
            expires_at=(
                row.expires_at.isoformat()
                if row.expires_at else None
            ),
        ), 201

    if code == PAID_CODE:
        paid_subscription = _active_paid_subscription(
            user.id,
            now,
        )

        if paid_subscription:
            return jsonify(
                status="ACTIVE",
                active=True,
                code=PAID_CODE,
                already_active=True,
                requires_plan_selection=False,
                expires_at=paid_subscription.expires_at.isoformat(),
            ), 200

        existing = active_entitlement(user.id, now)

        if existing:
            return jsonify(
                error="an_active_entitlement_already_exists",
                active_code=existing.code,
                expires_at=(
                    existing.expires_at.isoformat()
                    if existing.expires_at else None
                ),
            ), 409

        return jsonify(
            status="PLAN_SELECTION_REQUIRED",
            active=False,
            code=PAID_CODE,
            requires_plan_selection=True,
            plans=[
                {
                    "plan_code": "PLAN_15D",
                    "amount": 25,
                    "currency": "USD",
                    "duration_days": 15,
                },
                {
                    "plan_code": "PLAN_33D",
                    "amount": 50,
                    "currency": "USD",
                    "duration_days": 33,
                },
                {
                    "plan_code": "PLAN_70D",
                    "amount": 100,
                    "currency": "USD",
                    "duration_days": 70,
                },
            ],
        ), 200

    return jsonify(error="invalid_licence_code"), 400


@bp.get("/status")
@jwt_required()
def status():
    user = current_user()
    now = datetime.now(timezone.utc)

    row = active_entitlement(user.id, now)

    trial_uses = Entitlement.query.filter_by(
        user_id=user.id,
        code=TRIAL_CODE,
    ).count()

    paid_subscription = _active_paid_subscription(
        user.id,
        now,
    )

    if paid_subscription:
        active = True
        active_code = PAID_CODE
        expires_at = paid_subscription.expires_at
    else:
        active = bool(row)
        active_code = row.code if row else None
        expires_at = (
            row.expires_at if row else None
        )

    return jsonify(
        active=active,
        code=active_code,
        expires_at=(
            expires_at.isoformat()
            if expires_at else None
        ),
        trial_uses=trial_uses,
        trial_uses_remaining=max(
            0,
            MAX_TRIALS - trial_uses,
        ),
        paid_subscription_active=bool(paid_subscription),
    ), 200
