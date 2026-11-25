import hashlib, hmac, math
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, jsonify, current_app
from ..extensions import db
from ..models import TradingAccount, Command, AccountEvent, AccountTelemetry
from datetime import datetime, timezone, timedelta

bp=Blueprint("ea",__name__,url_prefix="/api/ea")

def authorized(account):
    token=request.headers.get("X-EA-Token", "")
    candidate=hashlib.sha256(token.encode()).hexdigest() if token else ""
    return bool(candidate and account.ea_token_hash and hmac.compare_digest(candidate,account.ea_token_hash))

@bp.get("/next")
def next_command():
    account_id=request.args.get("account_id",type=int)
    account=TradingAccount.query.get(account_id) if account_id else None
    if not account or not authorized(account): return jsonify(error="unauthorized"),401
    stale_before=datetime.now(timezone.utc)-timedelta(minutes=2)
    stale=Command.query.filter_by(account_id=account.id,status="CLAIMED").filter(Command.claimed_at<stale_before).all()
    for item in stale: item.status="PENDING"; item.claimed_at=None
    if stale: db.session.flush()
    row=Command.query.filter_by(account_id=account.id,status="PENDING").order_by(Command.id.asc()).with_for_update(skip_locked=True).first()
    if not row: return jsonify(command=None)
    row.status="CLAIMED"; row.claimed_at=datetime.now(timezone.utc); db.session.commit()
    return jsonify(command={"id":row.id,"command":row.command,"payload":row.payload})

@bp.post("/events")
def event():
    d=request.get_json(silent=True) or {}; account=TradingAccount.query.get(d.get("account_id"))
    if not account or not authorized(account): return jsonify(error="unauthorized"),401
    kind=str(d.get("event_type","telemetry"))[:40]
    payload=d.get("payload") or {}
    if not isinstance(payload,dict): return jsonify(error="event_payload_must_be_object"),400
    if kind=="heartbeat":
        account.last_seen=datetime.now(timezone.utc)
        row=AccountTelemetry.query.filter_by(account_id=account.id).first()
        if row is None: row=AccountTelemetry(account_id=account.id)
        amounts={}
        for field in ("balance","equity","free_margin","floating_pnl"):
            try: value=Decimal(str(payload.get(field,0) or 0))
            except (InvalidOperation,TypeError,ValueError): return jsonify(error="invalid_heartbeat_telemetry",field=field),400
            if not value.is_finite(): return jsonify(error="invalid_heartbeat_telemetry",field=field),400
            amounts[field]=value
        try: positions=int(payload.get("open_positions_count",0) or 0)
        except (TypeError,ValueError): return jsonify(error="invalid_heartbeat_telemetry",field="open_positions_count"),400
        enabled=payload.get("entries_enabled",False)
        connected=payload.get("connected_to_broker",False)
        if not isinstance(enabled,bool) or not isinstance(connected,bool) or positions<0 or positions>1000:
            return jsonify(error="invalid_heartbeat_telemetry"),400
        row.balance=amounts["balance"]; row.equity=amounts["equity"]
        row.free_margin=amounts["free_margin"]; row.floating_pnl=amounts["floating_pnl"]
        row.open_positions_count=positions
        row.active_symbol=str(payload.get("symbol",""))[:40]
        row.entries_enabled=enabled
        row.connected_to_broker=connected
        row.updated_at=datetime.now(timezone.utc)
        account.actual_state="CONNECTED" if connected else "DISCONNECTED"
        db.session.add(row)
    else:
        event_key=None
        if kind=="trade_deal" and str(payload.get("deal_id", "")).isdigit():
            event_key=f"{account.id}:deal:{payload.get('deal_id')}"
            existing=AccountEvent.query.filter_by(event_key=event_key).first()
            if existing: return jsonify(ok=True,duplicate=True),200
        row=AccountEvent(account_id=account.id,event_type=kind,payload=payload,event_key=event_key)
        db.session.add(row)
    if kind=="status": account.actual_state=str(payload.get("state","UNKNOWN"))[:20]
    db.session.commit(); return jsonify(ok=True)


@bp.post("/ack")
def acknowledge_command():
    d=request.get_json(silent=True) or {}
    account=TradingAccount.query.get(d.get("account_id"))
    if not account or not authorized(account): return jsonify(error="unauthorized"),401
    try: command_id=int(d.get("command_id"))
    except (TypeError,ValueError): return jsonify(error="invalid_command_id"),400
    row=Command.query.filter_by(id=command_id,account_id=account.id).first()
    if not row: return jsonify(error="command_not_found"),404
    if row.status=="DONE": return jsonify(ok=True,duplicate=True)
    if row.status!="CLAIMED": return jsonify(error="command_not_claimed"),409
    row.status="DONE"
    row.completed_at=datetime.now(timezone.utc)
    row.result=d.get("result") if isinstance(d.get("result"),dict) else {}
    db.session.commit()
    return jsonify(ok=True,status=row.status)


@bp.get("/permission")
def permission():
    account_id=request.args.get("account_id",type=int)
    account=TradingAccount.query.get(account_id) if account_id else None
    if not account or not authorized(account): return jsonify(error="unauthorized"),401
    from ..licences.service import can_start_new_entries
    live_allowed=(account.mode!="live" or current_app.config.get("ALLOW_LIVE_TRADING",False))
    allowed=(not account.is_deleted and live_allowed and account.desired_state=="RUNNING" and can_start_new_entries(account.owner_id))
    return jsonify(entries_allowed=bool(allowed),desired_state=account.desired_state,mode=account.mode,is_deleted=account.is_deleted)


@bp.post("/deals/batch")
def deals_batch():
    d=request.get_json(silent=True) or {}; account=TradingAccount.query.get(d.get("account_id"))
    if not account or not authorized(account): return jsonify(error="unauthorized"),401
    deals=d.get("deals")
    if not isinstance(deals,list) or len(deals)>1000: return jsonify(error="deals_must_be_array_max_1000"),400
    from decimal import Decimal,InvalidOperation
    from sqlalchemy.exc import IntegrityError
    normalized=[]; keys=[]; seen=set(); duplicates=0
    for item in deals:
        if not isinstance(item,dict): return jsonify(error="invalid_deal_record"),400
        deal_id=str(item.get("deal_id", ""))
        if not deal_id.isdigit() or len(deal_id)>32: return jsonify(error="invalid_deal_id"),400
        key=f"{account.id}:deal:{deal_id}"
        if key in seen: duplicates+=1; continue
        seen.add(key); keys.append(key)
        try:
            volume=Decimal(str(item.get("volume",0))); profit=Decimal(str(item.get("profit",0)))
            magic=int(item.get("magic",0)); entry=int(item.get("entry",0)); deal_time=int(item.get("time",0))
        except (InvalidOperation,TypeError,ValueError): return jsonify(error="invalid_deal_values"),400
        if not volume.is_finite() or not profit.is_finite() or volume<0 or abs(profit)>Decimal("1000000000"):
            return jsonify(error="invalid_deal_values"),400
        side=str(item.get("side","OTHER")).upper()
        if side not in {"BUY","SELL","OTHER"}: return jsonify(error="invalid_deal_side"),400
        symbol=str(item.get("symbol",""))[:40]
        normalized.append((key,{"deal_id":deal_id,"magic":magic,"symbol":symbol,"side":side,
            "volume":str(volume),"profit":str(profit),"entry":entry,"time":deal_time}))
    existing=set(x[0] for x in AccountEvent.query.filter(AccountEvent.event_key.in_(keys)).with_entities(AccountEvent.event_key).all()) if keys else set()
    rows=[]
    for key,payload in normalized:
        if key in existing: duplicates+=1; continue
        rows.append(AccountEvent(account_id=account.id,event_type="trade_deal",payload=payload,event_key=key))
    try:
        if rows: db.session.add_all(rows); db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # A concurrent replay is safe only when every deal key is now present.
        missing=[key for key,_ in normalized if not AccountEvent.query.filter_by(event_key=key).first()]
        if missing: return jsonify(error="batch_conflict_retry"),409
        return jsonify(ok=True,duplicate=True),200
    return jsonify(ok=True,inserted=len(rows),duplicates=duplicates),200
