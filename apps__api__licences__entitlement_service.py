"""Server-side entitlement grant and expiry operations."""
from datetime import datetime,timezone
from ..extensions import db
from ..models import Entitlement

def grant_paid_entitlement(user_id,expires_at):
    row=Entitlement(user_id=user_id,code="BOSSMODE30D",status="ACTIVE",expires_at=expires_at)
    db.session.add(row); return row

def expire_due_entitlements(now=None):
    now=now or datetime.now(timezone.utc)
    rows=Entitlement.query.filter(Entitlement.status=="ACTIVE",Entitlement.expires_at.isnot(None),Entitlement.expires_at<=now).all()
    for row in rows: row.status="EXPIRED"
    if rows: db.session.commit()
    return len(rows)

def revoke_user_entitlements(user_id,code=None):
    q=Entitlement.query.filter_by(user_id=user_id,status="ACTIVE")
    if code:q=q.filter_by(code=code)
    rows=q.all()
    for row in rows:row.status="REVOKED"
    if rows:db.session.commit()
    return len(rows)
