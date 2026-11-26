
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from ..models import Entitlement
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


@bp.post("/activate")
@jwt_required()
def activate():
    user = current_user()
    data = request.get_json(silent=True) or {}

    code = str(data.get("code", "")).strip().upper()
    now = datetime.now(timezone.utc)

    if not code:
        return jsonify(error="licence_code_required"), 400

    existing = active_entitlement(user.id, now)

    if existing:
        return jsonify(
            error="an_active_entitlement_already_exists",
            active_code=existing.code,
            expires_at=(
                existing.expires_at.isoformat()
                if existing.expires_at
                else None
            ),
        ), 409

    if code in VIP_CODES:
        from .activation_service import activate_vip_for_user

        try:
            activate_vip_for_user(user.id, code)
        except ValueError as exc:
            return jsonify(error=str(exc)), 403

        return jsonify(
            status="ACTIVE",
            code=code,
            expires_at=None,
        ), 200

    if code == TRIAL_CODE:
        from .activation_service import activate_trial_for_user

        row, error, eligible_at = activate_trial_for_user(
            user.id,
            now,
        )

        if error:
            return jsonify(
                error=error,
                eligible_at=(
                    eligible_at.isoformat()
                    if eligible_at
                    else None
                ),
            ), 409

        return jsonify(
            status="ACTIVE",
            code=row.code,
            expires_at=(
                row.expires_at.isoformat()
                if row.expires_at
                else None
            ),
        ), 201

    if code == PAID_CODE:
        return jsonify(
            error="paid_entitlement_is_activated_only_after_verified_payment"
        ), 403

    return jsonify(error="invalid_licence_code"), 400


@bp.get("/status")
@jwt_required()
def status():
    user = current_user()

    row = active_entitlement(user.id)

    trial_uses = Entitlement.query.filter_by(
        user_id=user.id,
        code=TRIAL_CODE,
    ).count()

    return jsonify(
        active=bool(row),
        code=row.code if row else None,
        expires_at=(
            row.expires_at.isoformat()
            if row and row.expires_at
            else None
        ),
        trial_uses=trial_uses,
        trial_uses_remaining=max(
            0,
            MAX_TRIALS - trial_uses,
        ),
    ), 200
