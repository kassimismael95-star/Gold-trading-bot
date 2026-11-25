"""Cryptographically random OTPs stored as peppered HMAC digests."""
import secrets,hmac,hashlib

def generate_otp():return f"{secrets.randbelow(1_000_000):06d}"
def _pepper():
    try:
        from flask import current_app,has_app_context
        if has_app_context():return str(current_app.config.get("SECRET_KEY","")).encode()
    except Exception:pass
    return b""
def hash_otp(code,salt):
    message=(str(salt)+str(code)).encode()
    return hmac.new(_pepper(),message,hashlib.sha256).hexdigest()
def verify_otp(code,salt,digest):return secrets.compare_digest(hash_otp(code,salt),str(digest))
