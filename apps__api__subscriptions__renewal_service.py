"""Renewal date calculation preserving unexpired customer time."""
from datetime import datetime,timezone
from ..models import Subscription,Entitlement

def renewal_start(user_id,now=None):
    now=now or datetime.now(timezone.utc)
    candidates=[]
    for row in Subscription.query.filter_by(user_id=user_id,status="ACTIVE").all():
        expiry=row.expires_at
        if expiry and expiry.tzinfo is None:expiry=expiry.replace(tzinfo=timezone.utc)
        if expiry and expiry>now:candidates.append(expiry)
    for row in Entitlement.query.filter_by(user_id=user_id,status="ACTIVE").all():
        expiry=row.expires_at
        if expiry and expiry.tzinfo is None:expiry=expiry.replace(tzinfo=timezone.utc)
        if expiry and expiry>now:candidates.append(expiry)
    return max([now]+candidates)
