from functools import wraps
from flask import current_app, request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from .models import User

def agent_required(fn):
    """Authenticate an enrolled agent with its unique secret, never bootstrap."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        import hashlib, hmac
        from .models import Agent
        agent_id=request.headers.get("X-Agent-ID","").strip()[:80]
        supplied=request.headers.get("X-Agent-Secret","")
        agent=Agent.query.filter_by(agent_id=agent_id).first() if agent_id else None
        candidate=hashlib.sha256(supplied.encode()).hexdigest() if supplied else ""
        if not agent or not agent.secret_hash or not candidate or not hmac.compare_digest(candidate,agent.secret_hash):
            return jsonify(error="agent_unauthorized"),401
        return fn(*args, **kwargs)
    return wrapper

def current_user():
    verify_jwt_in_request()
    return User.query.get(int(get_jwt_identity()))

def owner_account(fn):
    @wraps(fn)
    def wrapper(account_id, *args, **kwargs):
        user = current_user()
        from .models import TradingAccount
        account = TradingAccount.query.filter_by(id=account_id, owner_id=user.id).first()
        if not account:
            return jsonify(error="account_not_found"), 404
        return fn(account, *args, **kwargs)
    return wrapper
