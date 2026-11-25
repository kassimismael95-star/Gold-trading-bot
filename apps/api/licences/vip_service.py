"""Administrator assignment and customer activation of VIP entitlements."""
from ..extensions import db
from ..models import Entitlement
from .service import VIP_CODES

def assign_vip(user_id,code):
    code=str(code).upper()
    if code not in VIP_CODES:raise ValueError("invalid_vip_code")
    existing=Entitlement.query.filter(Entitlement.user_id==user_id,Entitlement.code==code,Entitlement.status.in_(["ACTIVE","ASSIGNED"])).first()
    if existing:raise ValueError("vip_already_active_or_assigned_for_user")
    row=Entitlement(user_id=user_id,code=code,status="ASSIGNED",expires_at=None)
    db.session.add(row);return row

def activate_assigned_vip(user_id,code):
    code=str(code).upper()
    if code not in VIP_CODES:raise ValueError("invalid_vip_code")
    row=Entitlement.query.filter_by(user_id=user_id,code=code,status="ASSIGNED").first()
    if not row:raise ValueError("vip_code_not_assigned_to_this_account")
    row.status="ACTIVE";db.session.commit();return row
