"""Opaque, high-entropy per-account worker tokens; store only SHA-256 hashes."""
import secrets,hashlib,hmac
def issue_token(): return secrets.token_urlsafe(40)
def token_hash(token): return hashlib.sha256(str(token).encode()).hexdigest()
def token_matches(token,stored_hash): return hmac.compare_digest(token_hash(token),str(stored_hash or ""))
