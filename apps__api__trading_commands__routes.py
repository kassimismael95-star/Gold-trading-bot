from flask import Blueprint, request, jsonify, current_app
from ..extensions import db
from ..models import Agent, TradingAccount, Command, AccountEvent
from ..security import agent_required
from datetime import datetime, timezone

bp=Blueprint("agent",__name__,url_prefix="/api/agent")

@bp.post("/commands/next")
@agent_required
def next_command():
    d=request.get_json(silent=True) or {}; aid=str(d.get("agent_id",""))
    if aid!=request.headers.get("X-Agent-ID",""): return jsonify(error="agent_identity_mismatch"),403
    account_id=d.get("account_id")
    q=Command.query.join(TradingAccount).filter(TradingAccount.agent_id==aid)
    if account_id: q=q.filter(Command.account_id==int(account_id))
    stale_before=datetime.now(timezone.utc)-__import__("datetime").timedelta(minutes=2)
    stale=q.filter(Command.status=="CLAIMED",Command.claimed_at<stale_before).all()
    for item in stale: item.status="PENDING"; item.claimed_at=None
    if stale: db.session.flush()
    row=q.filter(Command.status=="PENDING").order_by(Command.id.asc()).with_for_update(skip_locked=True).first()
    if not row: return jsonify(command=None)
    row.status="CLAIMED"; row.claimed_at=datetime.now(timezone.utc); db.session.commit()
    return jsonify(command={"id":row.id,"account_id":row.account_id,"command":row.command,"payload":row.payload})

@bp.post("/events")
@agent_required
def events():
    d=request.get_json(silent=True) or {}
    account=TradingAccount.query.get(d.get("account_id"))
    if not account: return jsonify(error="account_not_found"),404
    if account.agent_id != request.headers.get("X-Agent-ID") or account.agent_id != d.get("agent_id"): return jsonify(error="account_agent_mismatch"),403
    kind=str(d.get("event_type","telemetry"))[:40]
    row=AccountEvent(account_id=account.id,event_type=kind,payload=d.get("payload") or {})
    db.session.add(row)
    if kind=="status":
        account.actual_state=str((d.get("payload") or {}).get("state","UNKNOWN"))[:20]
    db.session.commit()
    return jsonify(ok=True)
