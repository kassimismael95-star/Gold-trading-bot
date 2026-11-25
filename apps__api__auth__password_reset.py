"""Password reset token policy; token delivery/storage should use a one-time DB challenge."""
import secrets,hashlib
from datetime import datetime,timezone,timedelta
def create_reset_token(): return secrets.token_urlsafe(32)
def digest_token(token): return hashlib.sha256(token.encode()).hexdigest()
def expiry(): return datetime.now(timezone.utc)+timedelta(minutes=30)
