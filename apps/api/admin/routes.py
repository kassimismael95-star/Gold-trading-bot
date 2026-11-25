from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from datetime import datetime, timezone
from ..security import current_user
from ..extensions import db
from ..models import User, Agent, TradingAccount, Entitlement, Command

bp=Blueprint("admin",__name__,url_prefix="/api/admin")

def admin_user():
    u=current_user()
    return u if u and u.role=="admin" else None

@bp.get("/overview")
@jwt_required()
def overview():
    if not admin_user(): return jsonify(error="forbidden"),403
    return jsonify(users=User.query.count(),agents=Agent.query.count(),accounts=TradingAccount.query.count())

@bp.post("/vip/assign")
@jwt_required()
def assign_vip():
    if not admin_user(): return jsonify(error="forbidden"),403
    d=request.get_json(silent=True) or {}
    email=str(d.get("email","")).strip().lower()
    code=str(d.get("code","")).strip().upper()
    if code not in {"BOSSMODE98","BOSSMODE99"} or not email:
        return jsonify(error="valid_email_and_vip_code_required"),400
    user=User.query.filter_by(email=email).first()
    if not user: return jsonify(error="user_not_found"),404
    from ..licences.vip_service import assign_vip
    try: entitlement=assign_vip(user.id,code)
    except ValueError as exc: return jsonify(error=str(exc)),409
    from ..security.audit_service import record_audit
    actor=admin_user()
    record_audit("licence.vip.assigned",actor.id,"user",user.id,{"code":code},request.remote_addr)
    db.session.commit()
    return jsonify(ok=True,email=email,code=code,status="ASSIGNED"),201


@bp.get("/customers")
@jwt_required()
def customers():
    if not admin_user(): return jsonify(error="forbidden"),403
    rows=User.query.order_by(User.id.desc()).limit(500).all()
    return jsonify(customers=[{"id":u.id,"email":u.email,"role":u.role,"email_verified":u.email_verified,"created_at":u.created_at.isoformat()} for u in rows])

@bp.get("/payments")
@jwt_required()
def payments():
    if not admin_user(): return jsonify(error="forbidden"),403
    from ..models import Payment
    rows=Payment.query.order_by(Payment.id.desc()).limit(500).all()
    return jsonify(payments=[{"id":p.id,"user_id":p.user_id,"tx_ref":p.tx_ref,"plan_code":p.plan_code,"amount":str(p.amount),"currency":p.currency,"status":p.status,"provider_id":p.provider_id,"created_at":p.created_at.isoformat()} for p in rows])

@bp.get("/accounts")
@jwt_required()
def accounts():
    if not admin_user(): return jsonify(error="forbidden"),403
    rows=TradingAccount.query.order_by(TradingAccount.id.desc()).limit(500).all()
    return jsonify(accounts=[{"id":a.id,"owner_id":a.owner_id,"label":a.label,"login":a.login,"server":a.server,"mode":a.mode,"agent_id":a.agent_id,"desired_state":a.desired_state,"actual_state":a.actual_state} for a in rows])

@bp.get("/agents")
@jwt_required()
def agents():
    if not admin_user(): return jsonify(error="forbidden"),403
    rows=Agent.query.order_by(Agent.id.desc()).all()
    return jsonify(agents=[{"id":a.id,"agent_id":a.agent_id,"hostname":a.hostname,"status":a.status,"capacity":a.capacity,"resource_capacity":(a.metrics or {}).get("recommended_capacity"),"metrics":a.metrics or {},"assigned_accounts":TradingAccount.query.filter_by(agent_id=a.agent_id).count(),"last_seen":a.last_seen.isoformat() if a.last_seen else None} for a in rows])

@bp.post("/payments/<int:payment_id>/refund")
@jwt_required()
def refund_payment(payment_id):
    actor=admin_user()
    if not actor: return jsonify(error="forbidden"),403
    d=request.get_json(silent=True) or {}
    try:
        from ..payments.refund_service import initiate_provider_refund
        row=initiate_provider_refund(payment_id,d.get("amount"),str(d.get("currency","USD")).upper(),str(d.get("comments","Customer refund")))
        from ..security.audit_service import record_audit
        record_audit("payment.refund.initiated",actor.id,"payment",payment_id,{"refund_id":row.id,"amount":str(row.amount),"currency":row.currency},request.remote_addr)
        db.session.commit()
        return jsonify(refund={"id":row.id,"provider_refund_id":row.provider_refund_id,"amount":str(row.amount),"currency":row.currency,"status":row.status}),202
    except ValueError as e: return jsonify(error=str(e)),400
    except Exception:
        db.session.rollback()
        return jsonify(error="refund_provider_failed"),502

@bp.get("/audit")
@jwt_required()
def audit_records():
    if not admin_user(): return jsonify(error="forbidden"),403
    from ..models import AuditLog
    rows=AuditLog.query.order_by(AuditLog.id.desc()).limit(300).all()
    return jsonify(events=[{"id":e.id,"actor_user_id":e.actor_user_id,"action":e.action,"target_type":e.target_type,"target_id":e.target_id,"details":e.details,"remote_addr":e.remote_addr,"created_at":e.created_at.isoformat()} for e in rows])


@bp.post("/vip/revoke")
@jwt_required()
def revoke_vip():
    actor=admin_user()
    if not actor: return jsonify(error="forbidden"),403
    d=request.get_json(silent=True) or {}
    try: user_id=int(d.get("user_id"))
    except (TypeError,ValueError): return jsonify(error="valid_user_id_required"),400
    code=str(d.get("code","" )).strip().upper()
    if code not in {"BOSSMODE98","BOSSMODE99"}: return jsonify(error="valid_vip_code_required"),400
    row=Entitlement.query.filter_by(user_id=user_id,code=code,status="ACTIVE").first()
    if not row: row=Entitlement.query.filter_by(user_id=user_id,code=code,status="ASSIGNED").first()
    if not row: return jsonify(error="vip_entitlement_not_found"),404
    row.status="REVOKED"
    from ..licences.service import active_entitlement
    accounts=TradingAccount.query.filter_by(owner_id=user_id).all()
    if active_entitlement(user_id) is None:
        for account in accounts:account.desired_state="STOPPED"
    from ..security.audit_service import record_audit
    record_audit("licence.vip.revoked",actor.id,"user",user_id,{"code":code,"accounts_stopped":0 if active_entitlement(user_id) else len(accounts)},request.remote_addr)
    db.session.commit()
    return jsonify(ok=True,status="REVOKED"),200


@bp.post("/agents/rotate-secret")
@jwt_required()
def rotate_agent_secret():
    actor=admin_user()
    if not actor: return jsonify(error="forbidden"),403
    d=request.get_json(silent=True) or {}
    agent_id=str(d.get("agent_id", "")).strip()[:80]
    agent=Agent.query.filter_by(agent_id=agent_id).first()
    if not agent: return jsonify(error="agent_not_found"),404
    secret=__import__("secrets").token_urlsafe(48)
    agent.secret_hash=__import__("hashlib").sha256(secret.encode()).hexdigest()
    agent.status="ONLINE"
    from ..security.audit_service import record_audit
    record_audit("agent.secret.rotated",actor.id,"agent",agent_id,{},request.remote_addr)
    db.session.commit()
    return jsonify(agent_id=agent_id,agent_secret=secret,notice="Secret shown once. Update the Oracle agent AGENT_SECRET immediately."),200


@bp.post("/accounts/<int:account_id>/reassign")
@jwt_required()
def reassign_account(account_id):
    actor=admin_user()
    if not actor: return jsonify(error="forbidden"),403
    account=TradingAccount.query.get(account_id)
    if not account: return jsonify(error="account_not_found"),404
    d=request.get_json(silent=True) or {}
    agent_id=str(d.get("agent_id", "")).strip()[:80]
    if agent_id:
        agent=Agent.query.filter_by(agent_id=agent_id).first()
        if not agent or not agent.secret_hash: return jsonify(error="enrolled_agent_required"),400
        assigned=TradingAccount.query.filter_by(agent_id=agent_id).count()
        configured=max(1,int(agent.capacity or 20));resource_cap=int((agent.metrics or {}).get("recommended_capacity",0) or 0)
        effective=min(configured,resource_cap) if resource_cap>0 else configured
        if account.agent_id!=agent_id and assigned>=effective: return jsonify(error="agent_capacity_reached",capacity=effective),409
    else: agent_id=None
    # Rotate EA token so the previous worker loses permission immediately.
    token=__import__("secrets").token_urlsafe(32)
    import hashlib
    from ..security.encryption import encrypt_secret
    account.ea_token_hash=hashlib.sha256(token.encode()).hexdigest()
    account.ea_token_ciphertext=encrypt_secret(token,f"ea-token:{account.id}")
    account.ea_token_version=(account.ea_token_version or 0)+1
    account.agent_id=agent_id
    account.desired_state="STOPPED"
    from ..security.audit_service import record_audit
    record_audit("account.agent.reassigned",actor.id,"account",account.id,{"agent_id":agent_id},request.remote_addr)
    db.session.commit()
    return jsonify(ok=True,account_id=account.id,agent_id=agent_id,ea_token=token,
      notice="Account reassigned and stopped. New EA token is shown once; it will be deployed to the new agent."),200


@bp.post("/accounts/<int:account_id>/risk-unlock")
@jwt_required()
def risk_unlock(account_id):
    actor=admin_user()
    if not actor: return jsonify(error="forbidden"),403
    account=TradingAccount.query.get(account_id)
    if not account: return jsonify(error="account_not_found"),404
    # Unlock does not start trading; customer must issue START separately.
    account.desired_state="STOPPED"
    row=Command(account_id=account.id,command="RISK_RESET",payload={"admin_user_id":actor.id})
    db.session.add(row)
    from ..security.audit_service import record_audit
    record_audit("account.risk_lock.cleared",actor.id,"account",account.id,{},request.remote_addr)
    db.session.commit()
    return jsonify(ok=True,command_id=row.id,status="PENDING",notice="Risk lock reset queued; account remains stopped until customer starts it."),202


@bp.get("/disputes")
@jwt_required()
def disputes():
    if not admin_user(): return jsonify(error="forbidden"),403
    from ..models import PaymentDispute
    rows=PaymentDispute.query.order_by(PaymentDispute.id.desc()).limit(300).all()
    return jsonify(disputes=[{"id":r.id,"payment_id":r.payment_id,"provider_case_id":r.provider_case_id,"status":r.status,"details":r.details,"created_at":r.created_at.isoformat()} for r in rows])


@bp.get("/refunds")
@jwt_required()
def refunds():
    if not admin_user(): return jsonify(error="forbidden"),403
    from ..models import PaymentRefund
    rows=PaymentRefund.query.order_by(PaymentRefund.id.desc()).limit(500).all()
    return jsonify(refunds=[{"id":r.id,"payment_id":r.payment_id,"provider_refund_id":r.provider_refund_id,"amount":str(r.amount),"currency":r.currency,"status":r.status,"created_at":r.created_at.isoformat()} for r in rows])


@bp.put("/agents/<string:agent_id>/capacity")
@jwt_required()
def set_agent_capacity(agent_id):
    actor=admin_user()
    if not actor:return jsonify(error="forbidden"),403
    agent=Agent.query.filter_by(agent_id=agent_id).first()
    if not agent:return jsonify(error="agent_not_found"),404
    d=request.get_json(silent=True) or {}
    try:capacity=int(d.get("capacity"))
    except (TypeError,ValueError):return jsonify(error="capacity_must_be_integer"),400
    if capacity<1 or capacity>1000:return jsonify(error="capacity_out_of_range",min=1,max=1000),400
    agent.capacity=capacity
    from ..security.audit_service import record_audit
    record_audit("agent.capacity.updated",actor.id,"agent",agent_id,{"capacity":capacity},request.remote_addr)
    db.session.commit()
    return jsonify(agent_id=agent_id,capacity=capacity),200

@bp.get("/subscriptions")
@jwt_required()
def subscriptions():
    if not admin_user():return jsonify(error="forbidden"),403
    from ..models import Subscription
    rows=Subscription.query.order_by(Subscription.id.desc()).limit(500).all()
    return jsonify(subscriptions=[{"id":r.id,"user_id":r.user_id,"payment_id":r.payment_id,"plan_code":r.plan_code,
      "status":r.status,"starts_at":r.starts_at.isoformat(),"expires_at":r.expires_at.isoformat()} for r in rows])

@bp.post("/subscriptions/<int:subscription_id>/extend")
@jwt_required()
def extend_subscription(subscription_id):
    actor=admin_user()
    if not actor:return jsonify(error="forbidden"),403
    from ..models import Subscription,Entitlement
    row=Subscription.query.get(subscription_id)
    if not row:return jsonify(error="subscription_not_found"),404
    d=request.get_json(silent=True) or {}
    try:days=int(d.get("days"))
    except (TypeError,ValueError):return jsonify(error="days_must_be_integer"),400
    if days<1 or days>365:return jsonify(error="days_out_of_range"),400
    now=datetime.now(timezone.utc);expiry=row.expires_at
    if expiry.tzinfo is None:expiry=expiry.replace(tzinfo=timezone.utc)
    start=max(now,expiry);new_expiry=start+__import__("datetime").timedelta(days=days)
    row.starts_at=start;row.expires_at=new_expiry;row.status="ACTIVE"
    entitlement=Entitlement.query.filter_by(user_id=row.user_id,code="BOSSMODE30D",status="ACTIVE").order_by(Entitlement.id.desc()).first()
    if entitlement:entitlement.expires_at=new_expiry
    else:db.session.add(Entitlement(user_id=row.user_id,code="BOSSMODE30D",status="ACTIVE",expires_at=new_expiry))
    from ..security.audit_service import record_audit
    record_audit("subscription.extended",actor.id,"subscription",row.id,{"days":days,"expires_at":new_expiry.isoformat()},request.remote_addr)
    db.session.commit()
    return jsonify(subscription_id=row.id,expires_at=new_expiry.isoformat()),200

@bp.post("/subscriptions/<int:subscription_id>/revoke")
@jwt_required()
def revoke_subscription(subscription_id):
    actor=admin_user()
    if not actor:return jsonify(error="forbidden"),403
    from ..models import Subscription,Entitlement
    row=Subscription.query.get(subscription_id)
    if not row:return jsonify(error="subscription_not_found"),404
    row.status="REVOKED"
    now=datetime.now(timezone.utc)
    others=Subscription.query.filter(Subscription.user_id==row.user_id,Subscription.id!=row.id,Subscription.status=="ACTIVE",Subscription.expires_at>now).all()
    paid=Entitlement.query.filter_by(user_id=row.user_id,code="BOSSMODE30D",status="ACTIVE").all()
    if others:
        latest=max(x.expires_at.replace(tzinfo=timezone.utc) if x.expires_at.tzinfo is None else x.expires_at for x in others)
        for ent in paid:ent.expires_at=latest
    else:
        for ent in paid:ent.status="REVOKED"
    from ..licences.service import active_entitlement
    has_other_entitlement=active_entitlement(row.user_id,now) is not None
    accounts=TradingAccount.query.filter_by(owner_id=row.user_id).all()
    if not has_other_entitlement:
        for account in accounts:account.desired_state="STOPPED"
    from ..security.audit_service import record_audit
    record_audit("subscription.revoked",actor.id,"subscription",row.id,{"accounts_stopped":0 if has_other_entitlement else len(accounts)},request.remote_addr)
    db.session.commit()
    return jsonify(ok=True,subscription_id=row.id,accounts_stopped=0 if has_other_entitlement else len(accounts)),200
