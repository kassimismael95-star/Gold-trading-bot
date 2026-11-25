"""Account recovery helpers designed for verified-email recovery."""
def normalize_email(value): return str(value or "").strip().lower()
def recovery_allowed(user, email_verified=False): return bool(user and email_verified and user.email)
