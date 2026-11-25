"""Expiry job callable from the managed maintenance loop."""
from .entitlement_service import expire_due_entitlements

def run_expiry(app):
    with app.app_context():return expire_due_entitlements()
