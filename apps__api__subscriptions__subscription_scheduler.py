"""Expiry scheduler entry point for cron/maintenance workers."""
from .expiry_service import expire_due

def run_expiry(app):
    with app.app_context():return expire_due()
