
"""Security services for credentials, tokens and authorization."""

import hashlib
import hmac
from functools import wraps

from flask import jsonify, request, current_app
from flask_jwt_extended import get_jwt_identity


def current_user():
    """Return the authenticated user associated with the current JWT."""
    from ..extensions import db
    from ..models import User

    identity = get_jwt_identity()

    if identity is None:
        return None

    try:
        user_id = int(identity)
    except (TypeError, ValueError):
        return None

    return db.session.get(User, user_id)


def owner_account(view_function):
    """Load an account and authorize its owner or an administrator."""

    @wraps(view_function)
    def decorated_function(*args, **kwargs):
        from ..extensions import db
        from ..models import TradingAccount
        from .permission_service import require_owner_or_admin

        account_id = (request.view_args or {}).get("account_id")

        if account_id is None:
            return jsonify(error="account_id_required"), 400

        account = db.session.get(TradingAccount, account_id)

        if account is None:
            return jsonify(error="account_not_found"), 404

        user = current_user()

        if user is None:
            return jsonify(error="authentication_required"), 401

        if not require_owner_or_admin(user, account):
            return jsonify(error="account_access_denied"), 403

        return view_function(account, *args, **kwargs)

    return decorated_function


def agent_required(view_function):
    """Authenticate an enrolled Oracle execution agent."""

    @wraps(view_function)
    def decorated_function(*args, **kwargs):
        from ..models import Agent

        agent_id = request.headers.get("X-Agent-ID", "").strip()[:80]
        supplied_secret = request.headers.get("X-Agent-Secret", "")

        if not agent_id or not supplied_secret:
            return jsonify(error="agent_unauthorized"), 401

        agent = Agent.query.filter_by(
            agent_id=agent_id
        ).first()

        if agent is None or not agent.secret_hash:
            return jsonify(error="agent_unauthorized"), 401

        candidate = hashlib.sha256(
            supplied_secret.encode("utf-8")
        ).hexdigest()

        if not hmac.compare_digest(candidate, agent.secret_hash):
            return jsonify(error="agent_unauthorized"), 401

        return view_function(*args, **kwargs)

    return decorated_function
