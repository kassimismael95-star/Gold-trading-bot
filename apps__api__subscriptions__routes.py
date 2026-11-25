from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from datetime import datetime,timezone
from ..security import current_user
from ..models import Subscription

bp=Blueprint("subscriptions",__name__,url_prefix="/api")
PLANS=[
 {"code":"PLAN_15D","amount":25.00,"currency":"USD","duration_days":15},
 {"code":"PLAN_33D","amount":50.00,"currency":"USD","duration_days":33},
 {"code":"PLAN_70D","amount":100.00,"currency":"USD","duration_days":70},
]
@bp.get("/plans")
def plans(): return jsonify(plans=PLANS)

@bp.get("/subscriptions/status")
@jwt_required()
def subscription_status():
    user=current_user(); now=datetime.now(timezone.utc)
    rows=Subscription.query.filter_by(user_id=user.id,status="ACTIVE").order_by(Subscription.expires_at.desc()).all()
    active=[]
    for row in rows:
        expiry=row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        if expiry>now:active.append((row,expiry))
    if not active:return jsonify(active=False,subscription=None),200
    row,expiry=active[0]
    return jsonify(active=True,subscription={"plan_code":row.plan_code,"status":row.status,"starts_at":row.starts_at.isoformat(),
      "expires_at":expiry.isoformat(),"days_remaining":max(0,(expiry-now).days)}),200
