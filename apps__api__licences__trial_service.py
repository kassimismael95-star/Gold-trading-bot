"""Trial lifecycle policy: 24h access, 96h cooldown after expiry, two uses."""
from datetime import datetime,timezone,timedelta
from ..extensions import db
from ..models import Entitlement
from .service import TRIAL_CODE,TRIAL_HOURS,TRIAL_COOLDOWN_HOURS,MAX_TRIALS

def activate_trial(user_id,now=None):
    now=now or datetime.now(timezone.utc)
    trials=Entitlement.query.filter_by(user_id=user_id,code=TRIAL_CODE).order_by(Entitlement.id.asc()).all()
    if len(trials)>=MAX_TRIALS:return None,"trial_limit_reached",None
    if trials:
        expiry=trials[-1].expires_at
        if expiry is None:return None,"trial_history_invalid",None
        if expiry.tzinfo is None:expiry=expiry.replace(tzinfo=timezone.utc)
        eligible=expiry+timedelta(hours=TRIAL_COOLDOWN_HOURS)
        if now<eligible:return None,"trial_cooldown_active",eligible
    row=Entitlement(user_id=user_id,code=TRIAL_CODE,status="ACTIVE",expires_at=now+timedelta(hours=TRIAL_HOURS))
    db.session.add(row);db.session.commit();return row,None,None
