"""Mark due paid subscription and entitlement records expired."""
from datetime import datetime,timezone
from ..extensions import db
from ..models import Subscription,Entitlement

def expire_due(now=None):
    now=now or datetime.now(timezone.utc)
    subscriptions=Subscription.query.filter(Subscription.status=="ACTIVE",Subscription.expires_at<=now).all()
    entitlements=Entitlement.query.filter(Entitlement.status=="ACTIVE",Entitlement.expires_at.isnot(None),Entitlement.expires_at<=now).all()
    for row in subscriptions:row.status="EXPIRED"
    for row in entitlements:row.status="EXPIRED"
    if subscriptions or entitlements:db.session.commit()
    return {"subscriptions":len(subscriptions),"entitlements":len(entitlements)}
