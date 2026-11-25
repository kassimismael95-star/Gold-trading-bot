"""Append-only application audit records for privileged/security actions."""
from ..extensions import db
from ..models import AuditLog

def record_audit(action, actor_user_id=None, target_type=None, target_id=None, details=None, remote_addr=None):
    row = AuditLog(actor_user_id=actor_user_id, action=str(action)[:80],
        target_type=str(target_type)[:40] if target_type else None,
        target_id=str(target_id)[:80] if target_id is not None else None,
        details=details if isinstance(details, dict) else {},
        remote_addr=str(remote_addr)[:64] if remote_addr else None)
    db.session.add(row)
    return row
