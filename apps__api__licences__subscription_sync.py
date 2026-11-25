"""Keep paid entitlement expiry aligned with the payment-linked subscription."""
from ..extensions import db
from ..models import Entitlement

def sync_paid_entitlement(user_id,expires_at):
    row=Entitlement.query.filter_by(user_id=user_id,code="BOSSMODE30D",status="ACTIVE").order_by(Entitlement.id.desc()).first()
    if row is None:
        row=Entitlement(user_id=user_id,code="BOSSMODE30D",status="ACTIVE",expires_at=expires_at);db.session.add(row)
    else:row.expires_at=expires_at
    return row
