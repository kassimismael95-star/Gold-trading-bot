"""Email challenge policy helpers."""
from datetime import datetime,timezone,timedelta
from .otp_service import generate_otp,hash_otp,verify_otp
TTL=timedelta(minutes=10); RESEND_COOLDOWN=timedelta(seconds=60); MAX_ATTEMPTS=5
def issue(salt):
 code=generate_otp(); return code,hash_otp(code,salt),datetime.now(timezone.utc)+TTL
def challenge_valid(expires_at,attempts):
 now=datetime.now(timezone.utc); expiry=expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
 return now<expiry and attempts<MAX_ATTEMPTS
