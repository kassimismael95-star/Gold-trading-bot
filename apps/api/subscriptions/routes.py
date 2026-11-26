
import json
from pathlib import Path
from datetime import datetime, timezone

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from ..security import current_user
from ..models import Subscription


bp = Blueprint("subscriptions", __name__, url_prefix="/api")

# Repository root / config / subscription_plans.json
PLANS_FILE = Path(__file__).resolve().parents[3] / "config" / "subscription_plans.json"


def load_plans():
    """Load subscription plans from the repository's shared plan config."""
    with PLANS_FILE.open("r", encoding="utf-8") as file:
        configured = json.load(file)

    plans = []

    for code, plan in configured.items():
        amount = float(plan["amount"])
        currency = str(plan["currency"]).upper()
        duration_days = int(plan["duration_days"])

        if amount <= 0 or duration_days <= 0:
            raise ValueError(f"Invalid subscription plan: {code}")

        plans.append({
            "code": code,
            "amount": amount,
            "currency": currency,
            "duration_days": duration_days,
        })

    return plans


@bp.get("/plans")
def plans():
    try:
        return jsonify(plans=load_plans())
    except Exception:
        from flask import current_app
        current_app.logger.exception("Could not load subscription plans")
        return jsonify(error="plans_unavailable"), 500


@bp.get("/subscriptions/status")
@jwt_required()
def subscription_status():
    user = current_user()
    now = datetime.now(timezone.utc)

    rows = (
        Subscription.query
        .filter_by(user_id=user.id, status="ACTIVE")
        .order_by(Subscription.expires_at.desc())
        .all()
    )

    active = []

    for row in rows:
        expiry = row.expires_at

        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        if expiry > now:
            active.append((row, expiry))

    if not active:
        return jsonify(active=False, subscription=None), 200

    row, expiry = active[0]

    return jsonify(
        active=True,
        subscription={
            "plan_code": row.plan_code,
            "status": row.status,
            "starts_at": row.starts_at.isoformat(),
            "expires_at": expiry.isoformat(),
            "days_remaining": max(0, (expiry - now).days),
        },
    ), 200
