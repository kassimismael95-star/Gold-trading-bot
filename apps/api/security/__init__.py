
"""Security services for credentials, tokens and authorization."""

from functools import wraps

from flask import jsonify, request
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
