"""Single entry point for licence activation policy."""
from .trial_service import activate_trial
from .vip_service import activate_assigned_vip

def activate_trial_for_user(user_id,now=None):return activate_trial(user_id,now)
def activate_vip_for_user(user_id,code):return activate_assigned_vip(user_id,code)
