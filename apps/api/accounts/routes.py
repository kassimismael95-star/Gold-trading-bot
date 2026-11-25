from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required
import secrets, hashlib
from ..extensions import db
from ..models import TradingAccount, Command, AccountEvent, AccountCredential
from ..security import current_user, owner_account
from ..licences.service import can_start_new_entries

bp = Blueprint("accounts", __name__, url_prefix="/api/accounts")

@bp.get("")
@jwt_required()
def list_accounts():
    user=current_user()
    rows=TradingAccount.query.filter_by(owner_id=user.id).all()
    from ..models import AccountTelemetry
    telemetry={t.account_id:t for t in AccountTelemetry.query.filter(AccountTelemetry.account_id.in_([x.id for x in rows])).all()} if rows else {}
    return jsonify(accounts=[serialize(x,telemetry.get(x.id)) for x in rows])

@bp.post("")
@jwt_required()
def create_account():
    user=current_user(); d=request.get_json(silent=True) or {}
    required=("label","login","server","mt5_password")
    if any(not str(d.get(k,"")).strip() for k in required):
        return jsonify(error="label_login_server_and_mt5_password_required"),400
    login=str(d.get("login", "")); server=str(d.get("server", "")).strip(); symbol=str(d.get("symbol","AUTO")).strip()
    import re
    if not login.isdigit() or len(login)>40: return jsonify(error="mt5_login_must_be_numeric"),400
    if not re.fullmatch(r"[A-Za-z0-9 ._-]{1,120}",server): return jsonify(error="valid_mt5_server_required"),400
    if not re.fullmatch(r"AUTO|[A-Za-z0-9._-]{1,40}",symbol): return jsonify(error="valid_mt5_symbol_required"),400
    mode=str(d.get("mode","demo")).lower()
    if mode not in ("demo","live"): return jsonify(error="mode_must_be_demo_or_live"),400
    if mode=="live": return jsonify(error="live_account_registration_locked_until_demo_acceptance_and_admin_enablement"),403
    mt5_password=str(d.get("mt5_password", ""))
    if not mt5_password or len(mt5_password)>512 or "\r" in mt5_password or "\n" in mt5_password: return jsonify(error="valid_mt5_password_required"),400
    from ..security.credential_vault import seal_mt5_password
    ea_token=secrets.token_urlsafe(32)
    from ..security.encryption import encrypt_secret
    row=TradingAccount(owner_id=user.id,label=str(d["label"])[:80],login=str(d["login"]),server=str(d["server"]),broker=str(d.get("broker","Exness")),mode=mode,symbol=str(d.get("symbol","AUTO")),agent_id=None,ea_token_hash=hashlib.sha256(ea_token.encode()).hexdigest())
    db.session.add(row); db.session.flush()
    row.ea_token_ciphertext=encrypt_secret(ea_token,f"ea-token:{row.id}")
    db.session.add(AccountCredential(account_id=row.id,password_ciphertext=seal_mt5_password(mt5_password,row.id)))
    from ..security.audit_service import record_audit
    record_audit("account.created",user.id,"account",row.id,{"mode":mode},request.remote_addr)
    db.session.commit()
    return jsonify(account=serialize(row),ea_token=ea_token,ea_token_notice="Copy this token into the EA input once. It is shown only at creation."),201



@bp.post("/<int:account_id>/ea-token/regenerate")
@jwt_required()
@owner_account
def regenerate_ea_token(account):
    ea_token=secrets.token_urlsafe(32)
    from ..security.encryption import encrypt_secret
    account.ea_token_hash=hashlib.sha256(ea_token.encode()).hexdigest()
    account.ea_token_ciphertext=encrypt_secret(ea_token,f"ea-token:{account.id}")
    account.ea_token_version=(account.ea_token_version or 0)+1
    account.desired_state="STOPPED"
    from ..security.audit_service import record_audit
    record_audit("account.ea_token.rotated",current_user().id,"account",account.id,{},request.remote_addr)
    db.session.commit()
    return jsonify(ea_token=ea_token,notice="Old EA token is now invalid. Copy this token into the EA input."),200

@bp.get("/<int:account_id>/status")
@jwt_required()
@owner_account
def status(account):
    events=AccountEvent.query.filter_by(account_id=account.id).order_by(AccountEvent.id.desc()).limit(10).all()
    return jsonify(account=serialize(account),events=[{"type":e.event_type,"payload":e.payload,"at":e.created_at.isoformat()} for e in events])

@bp.post("/<int:account_id>/commands")
@jwt_required()
@owner_account
def command(account):
    d=request.get_json(silent=True) or {}; name=str(d.get("command"," ")).strip().upper()
    if name not in ("START","STOP","CLOSE_ALL","SETTINGS","EMERGENCY_STOP"):
        return jsonify(error="unsupported_command"),400
    if name=="START" and account.mode=="live" and not current_app.config.get("ALLOW_LIVE_TRADING",False):
        return jsonify(error="live_trading_not_enabled"),403
    if name=="START" and not can_start_new_entries(account.owner_id):
        return jsonify(error="active_licence_or_subscription_required"),403
    payload=d.get("payload") or {}
    if not isinstance(payload,dict): return jsonify(error="command_payload_must_be_object"),400
    if name=="SETTINGS":
        allowed={"basket_profit_target_usd","basket_loss_limit_usd","max_drawdown_percent","max_positions","one_entry_per_m1_bar","news_filter_enabled","news_minutes_before","news_minutes_after","session_filter_enabled","session_start_hour","session_end_hour","require_candle_confirmation"}
        unsupported=set(payload)-allowed
        if unsupported: return jsonify(error="unsupported_setting",keys=sorted(unsupported)),400
        current={"basket_profit_target_usd":5.0,"basket_loss_limit_usd":20.0,
            "max_drawdown_percent":35.0,"max_positions":0,"one_entry_per_m1_bar":False,
            "news_filter_enabled":False,"news_minutes_before":15,"news_minutes_after":15,
            "session_filter_enabled":False,"session_start_hour":0,"session_end_hour":24,
            "require_candle_confirmation":True}
        current.update(account.risk_settings or {})
        numeric_ranges={"basket_profit_target_usd":(0.0,1000.0),"basket_loss_limit_usd":(1.0,10000.0),"max_drawdown_percent":(1.0,35.0),"max_positions":(0,20),"news_minutes_before":(0,240),"news_minutes_after":(0,240),"session_start_hour":(0,23),"session_end_hour":(0,24)}
        for key,value in payload.items():
            if key in {"one_entry_per_m1_bar","news_filter_enabled","session_filter_enabled","require_candle_confirmation"}:
                if not isinstance(value,bool): return jsonify(error="boolean_setting_required",key=key),400
                current[key]=value; continue
            lo,hi=numeric_ranges[key]
            try: number=float(value)
            except (TypeError,ValueError): return jsonify(error="invalid_setting_value",key=key),400
            if not lo<=number<=hi: return jsonify(error="setting_out_of_range",key=key,min=lo,max=hi),400
            if key in {"max_positions","news_minutes_before","news_minutes_after","session_start_hour","session_end_hour"} and int(number)!=number: return jsonify(error="setting_must_be_integer",key=key),400
            current[key]=int(number) if key in {"max_positions","news_minutes_before","news_minutes_after","session_start_hour","session_end_hour"} else number
        account.risk_settings=current; payload=current
    if name=="START": account.desired_state="RUNNING"
    if name in ("STOP","CLOSE_ALL","EMERGENCY_STOP"): account.desired_state="STOPPED"
    if name=="EMERGENCY_STOP": payload={**payload,"policy":"STOP_NEW_ENTRIES_MANAGE_EXISTING"}
    row=Command(account_id=account.id,command=name,payload=payload)
    db.session.add(row)
    from ..security.audit_service import record_audit
    record_audit("account.command.queued",current_user().id,"account",account.id,{"command":name},request.remote_addr)
    db.session.commit()
    return jsonify(command_id=row.id,status=row.status,desired_state=account.desired_state),202

@bp.put("/<int:account_id>/credentials")
@jwt_required()
@owner_account
def update_credentials(account):
    d=request.get_json(silent=True) or {}; password=str(d.get("mt5_password", ""))
    if not password or len(password)>512 or "\r" in password or "\n" in password: return jsonify(error="valid_mt5_password_required"),400
    from ..security.credential_vault import seal_mt5_password
    row=AccountCredential.query.filter_by(account_id=account.id).first()
    if row is None: row=AccountCredential(account_id=account.id,password_ciphertext=seal_mt5_password(password,account.id))
    else: row.password_ciphertext=seal_mt5_password(password,account.id); row.version+=1; row.revoked=False
    account.desired_state="STOPPED"
    db.session.add(row)
    from ..security.audit_service import record_audit
    record_audit("account.credentials.updated",current_user().id,"account",account.id,{"credential_version":row.version},request.remote_addr)
    db.session.commit()
    return jsonify(ok=True,credential_version=row.version)

@bp.delete("/<int:account_id>/credentials")
@jwt_required()
@owner_account
def revoke_credentials(account):
    row=AccountCredential.query.filter_by(account_id=account.id).first()
    if row:
        row.revoked=True; row.version+=1; account.desired_state="STOPPED"
        from ..security.audit_service import record_audit
        record_audit("account.credentials.revoked",current_user().id,"account",account.id,{},request.remote_addr)
        db.session.commit()
    return jsonify(ok=True,revoked=True)


def serialize(a,telemetry=None):
    actual="REMOVED" if a.is_deleted and a.agent_id is None else a.actual_state
    if a.last_seen and not (a.is_deleted and a.agent_id is None):
        from datetime import datetime,timezone,timedelta
        seen=a.last_seen if a.last_seen.tzinfo else a.last_seen.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc)-seen>timedelta(seconds=90): actual="STALE"
    live={"balance":str(telemetry.balance),"equity":str(telemetry.equity),"free_margin":str(telemetry.free_margin),
      "floating_pnl":str(telemetry.floating_pnl),"open_positions_count":telemetry.open_positions_count,
      "active_symbol":telemetry.active_symbol,"entries_enabled":telemetry.entries_enabled,"connected_to_broker":telemetry.connected_to_broker,
      "updated_at":telemetry.updated_at.isoformat()} if telemetry else None
    return {"id":a.id,"label":a.label,"broker":a.broker,"login":a.login,"server":a.server,"mode":a.mode,
      "symbol":a.symbol,"desired_state":a.desired_state,"actual_state":actual,"agent_id":a.agent_id,"is_deleted":a.is_deleted,
      "risk_settings":a.risk_settings or {},"telemetry":live,"last_seen":a.last_seen.isoformat() if a.last_seen else None}


@bp.delete("/<int:account_id>")
@jwt_required()
def delete_account(account_id):
    user=current_user();account=TradingAccount.query.filter_by(id=account_id,owner_id=user.id).first()
    if not account:return jsonify(error="account_not_found"),404
    if account.is_deleted:return jsonify(ok=True,removal_pending=bool(account.agent_id),status="REMOVING" if account.agent_id else "REMOVED"),200
    from ..models import AccountTelemetry
    telemetry=AccountTelemetry.query.filter_by(account_id=account.id).first()
    recent=False
    if telemetry and telemetry.updated_at:
        from datetime import datetime,timezone,timedelta
        updated=telemetry.updated_at if telemetry.updated_at.tzinfo else telemetry.updated_at.replace(tzinfo=timezone.utc)
        recent=datetime.now(timezone.utc)-updated<=timedelta(seconds=90)
    can_detach=(account.agent_id is None) or (telemetry and recent and telemetry.connected_to_broker and telemetry.open_positions_count==0)
    account.is_deleted=True;account.desired_state="STOPPED"
    if can_detach:
        account.agent_id=None;account.actual_state="REMOVED"
        credential=AccountCredential.query.filter_by(account_id=account.id).first()
        if credential:credential.revoked=True;credential.version+=1
        import hashlib,secrets
        account.ea_token_hash=hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest()
        account.ea_token_ciphertext=None;account.ea_token_version+=1
    from ..security.audit_service import record_audit
    record_audit("account.removal.requested",user.id,"account",account.id,{"detached":bool(can_detach),"open_positions":telemetry.open_positions_count if telemetry else None},request.remote_addr)
    if can_detach:record_audit("account.removal.completed",user.id,"account",account.id,{},request.remote_addr)
    db.session.commit()
    return jsonify(ok=True,removal_pending=bool(account.agent_id),status="REMOVING" if account.agent_id else "REMOVED",
        open_positions=telemetry.open_positions_count if telemetry else None),202
