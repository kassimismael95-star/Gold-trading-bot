from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from ..security import current_user
from ..models import TradingAccount, Entitlement, AccountTelemetry
from datetime import datetime, timezone
bp=Blueprint("dashboard",__name__,url_prefix="/api/dashboard")
@bp.get("/summary")
@jwt_required()
def summary():
    u=current_user()
    accounts=TradingAccount.query.filter_by(owner_id=u.id).all()
    ent=Entitlement.query.filter_by(user_id=u.id,status="ACTIVE").order_by(Entitlement.id.desc()).first()
    telemetry={t.account_id:t for t in AccountTelemetry.query.filter(AccountTelemetry.account_id.in_([a.id for a in accounts])).all()} if accounts else {}
    ent_expiry=ent.expires_at if ent and ent.expires_at else None
    if ent_expiry and ent_expiry.tzinfo is None: ent_expiry=ent_expiry.replace(tzinfo=timezone.utc)
    return jsonify(accounts_total=len(accounts),accounts=[{"id":a.id,"label":a.label,"state":a.actual_state,"mode":a.mode,
      "desired_state":a.desired_state,"risk_settings":a.risk_settings or {},
      "telemetry":({"balance":str(telemetry[a.id].balance),"equity":str(telemetry[a.id].equity),
        "free_margin":str(telemetry[a.id].free_margin),"floating_pnl":str(telemetry[a.id].floating_pnl),
        "open_positions_count":telemetry[a.id].open_positions_count,"active_symbol":telemetry[a.id].active_symbol,
        "entries_enabled":telemetry[a.id].entries_enabled,"connected_to_broker":telemetry[a.id].connected_to_broker,"updated_at":telemetry[a.id].updated_at.isoformat()} if a.id in telemetry else None)} for a in accounts],
      entitlement_active=bool(ent and (not ent_expiry or ent_expiry>datetime.now(timezone.utc))),entitlement_code=ent.code if ent else None,entitlement_expires_at=ent_expiry.isoformat() if ent_expiry else None)


@bp.get("/payments")
@jwt_required()
def payment_history():
    from ..models import Payment
    u=current_user()
    rows=Payment.query.filter_by(user_id=u.id).order_by(Payment.id.desc()).limit(100).all()
    return jsonify(payments=[{"tx_ref":p.tx_ref,"plan_code":p.plan_code,"amount":str(p.amount),"currency":p.currency,"status":p.status,"created_at":p.created_at.isoformat()} for p in rows])


@bp.get("/trades")
@jwt_required()
def trade_history():
    from ..models import AccountEvent
    u=current_user()
    ids=[a.id for a in TradingAccount.query.filter_by(owner_id=u.id).all()]
    if not ids: return jsonify(trades=[])
    rows=AccountEvent.query.filter(AccountEvent.account_id.in_(ids),AccountEvent.event_type=="trade_deal").order_by(AccountEvent.id.desc()).limit(300).all()
    return jsonify(trades=[{"account_id":e.account_id,"payload":e.payload,"created_at":e.created_at.isoformat()} for e in rows])
