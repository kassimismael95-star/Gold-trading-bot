
"""Public subscription plans and authenticated subscription status."""

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from ..security import current_user
from ..models import Subscription


bp = Blueprint("subscriptions", __name__, url_prefix="/api")


def _utc(value):
    """Normalize database timestamps to timezone-aware UTC."""
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _load_plans():
    """Load the configured subscription plans from the project config."""
    project_root = Path(__file__).resolve().parents[3]
    config_path = project_root / "config" / "subscription_plans.json"

    with config_path.open("r", encoding="utf-8") as file:
        configured = json.load(file)

    plans = []

    for code, details in configured.items():
        plans.append({
            "code": code,
            "amount": details["amount"],
            "currency": details["currency"],
            "duration_days": details["duration_days"],
        })

    return plans


@bp.get("/plans")
def plans():
    try:
        return jsonify(plans=_load_plans()), 200
    except (OSError, ValueError, KeyError, TypeError):
        return jsonify(error="subscription_plans_unavailable"), 500


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
        expiry = _utc(row.expires_at)

        if expiry and expiry > now:
            active.append((row, expiry))

    if not active:
        return jsonify(
            active=False,
            subscription=None,
        ), 200

    row, expiry = active[0]
    starts_at = _utc(row.starts_at)

    return jsonify(
        active=True,
        subscription={
            "plan_code": row.plan_code,
            "status": row.status,
            "starts_at": (
                starts_at.isoformat()
                if starts_at
                else None
            ),
            "expires_at": expiry.isoformat(),
            "days_remaining": max(
                0,
                (expiry - now).days,
            ),
        },
    ), 200
