from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from datetime import datetime, timedelta, timezone
from ..extensions import db
from ..models import Entitlement
from ..security import current_user
from .service import VIP_CODES, TRIAL_CODE, PAID_CODE, TRIAL_HOURS, TRIAL_COOLDOWN_HOURS, MAX_TRIALS, active_entitlement

bp=Blueprint("licences",__name__,url_prefix="/api/licences")

@bp.post("/activate")
@jwt_required()
def activate():
    user=current_user(); d=request.get_json(silent=True) or {}; code=str(d.get("code","")).strip().upper()
    now=datetime.now(timezone.utc)
    if active_entitlement(user.id, now):
        return jsonify(error="an_active_entitlement_already_exists"),409
    if code in VIP_CODES:
        from .activation_service import activate_vip_for_user
        try: assigned=activate_vip_for_user(user.id,code)
        except ValueError as exc: return jsonify(error=str(exc)),403
        return jsonify(status="ACTIVE",code=code,expires_at=None),200
    if code==TRIAL_CODE:
        from .activation_service import activate_trial_for_user
        row,error,eligible=activate_trial_for_user(user.id,now)
        if error:
            status_code=409
            return jsonify(error=error,eligible_at=eligible.isoformat() if eligible else None),status_code
    elif code==PAID_CODE:
        return jsonify(error="paid_entitlement_is_activated_only_after_verified_payment"),403
    else:
        return jsonify(error="invalid_licence_code"),400
    return jsonify(status="ACTIVE",code=row.code,expires_at=row.expires_at.isoformat()),201

@bp.get("/status")
@jwt_required()
def status():
    user=current_user(); row=active_entitlement(user.id)
    trials=Entitlement.query.filter_by(user_id=user.id,code=TRIAL_CODE).count()
    return jsonify(active=bool(row),code=row.code if row else None,
      expires_at=row.expires_at.isoformat() if row and row.expires_at else None,
      trial_uses=trials,trial_uses_remaining=max(0,MAX_TRIALS-trials))
