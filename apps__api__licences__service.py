from datetime import datetime, timezone
from ..models import Entitlement

VIP_CODES = {"BOSSMODE98", "BOSSMODE99"}
TRIAL_CODE = "BOSSMODE01D"
PAID_CODE = "BOSSMODE30D"
TRIAL_HOURS = 24
TRIAL_COOLDOWN_HOURS = 96
MAX_TRIALS = 2

def active_entitlement(user_id, now=None):
    now = now or datetime.now(timezone.utc)
    rows = Entitlement.query.filter_by(user_id=user_id, status="ACTIVE").order_by(Entitlement.id.desc()).all()
    for row in rows:
        expiry = row.expires_at
        if expiry is None or _aware(expiry) > now:
            return row
    return None

def _aware(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

def can_start_new_entries(user_id, now=None):
    return active_entitlement(user_id, now) is not None
