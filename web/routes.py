"""
Web API routes.

Authentication endpoints are functional. Trading endpoints are
intentionally gated until server-side license entitlement is wired in.
"""

from flask import Blueprint, jsonify, request

from accounts.account_registry import (
    add_account,
    get_account,
    list_accounts,
    update_account_status
)
from core.license_manager import validate_license
from execution.command_queue import get_command_status
from web.auth import (
    create_session,
    require_authenticated_user,
    sign_out
)
from database.models import create_user, find_user_by_email


api = Blueprint("api", __name__)


@api.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok"
    })


@api.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({
            "error": "Email and password are required."
        }), 400

    if find_user_by_email(email):
        return jsonify({
            "error": "An account with this email already exists."
        }), 409

    user = create_user(email, password)

    return jsonify({
        "user_id": user["id"],
        "email": user["email"]
    }), 201


@api.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = find_user_by_email(email)

    if not user or not user["password_hash"]:
        return jsonify({
            "error": "Invalid email or password."
        }), 401

    from werkzeug.security import check_password_hash

    if not check_password_hash(
        user["password_hash"],
        password
    ):
        return jsonify({
            "error": "Invalid email or password."
        }), 401

    session = create_session(user["id"])

    response = jsonify({
        "user_id": user["id"],
        "email": user["email"]
    })

    response.set_cookie(
        "session_token",
        session["session_token"],
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=30 * 24 * 60 * 60
    )

    return response


@api.route("/api/auth/me", methods=["GET"])
def me():
    try:
        session = require_authenticated_user(request)
    except PermissionError as error:
        return jsonify({
            "error": str(error)
        }), 401

    return jsonify({
        "user_id": session["user_id"],
        "email": session["email"]
    })


@api.route("/api/auth/logout", methods=["POST"])
def logout():
    session_token = request.cookies.get("session_token")

    sign_out(session_token)

    response = jsonify({
        "status": "signed_out"
    })

    response.delete_cookie("session_token")

    return response


@api.route("/api/accounts", methods=["GET"])
def get_accounts():
    try:
        session = require_authenticated_user(request)
    except PermissionError as error:
        return jsonify({
            "error": str(error)
        }), 401

    accounts = list_accounts(session["user_id"])

    return jsonify({
        "accounts": accounts
    })


@api.route("/api/accounts", methods=["POST"])
def register_account():
    try:
        session = require_authenticated_user(request)
    except PermissionError as error:
        return jsonify({
            "error": str(error)
        }), 401

    data = request.get_json(silent=True) or {}

    required_fields = [
        "broker_name",
        "login",
        "password",
        "server_name"
    ]

    if any(not data.get(field) for field in required_fields):
        return jsonify({
            "error": "Broker name, login, password, and server are required."
        }), 400

    account = add_account(
        user_id=session["user_id"],
        broker_name=data["broker_name"],
        login=data["login"],
        password=data["password"],
        server_name=data["server_name"]
    )

    return jsonify({
        "account_id": account["id"],
        "status": account["status"]
    }), 201


@api.route("/api/accounts/<int:account_id>", methods=["GET"])
def get_account_details(account_id):
    try:
        session = require_authenticated_user(request)
    except PermissionError as error:
        return jsonify({
            "error": str(error)
        }), 401

    account = get_account(
        session["user_id"],
        account_id
    )

    if not account:
        return jsonify({
            "error": "Account not found."
        }), 404

    return jsonify(account)


@api.route("/api/accounts/<int:account_id>/status", methods=["POST"])
def change_account_status(account_id):
    try:
        session = require_authenticated_user(request)
    except PermissionError as error:
        return jsonify({
            "error": str(error)
        }), 401

    data = request.get_json(silent=True) or {}

    status = data.get("status")

    if status not in {"ACTIVE", "INACTIVE", "ERROR"}:
        return jsonify({
            "error": "Invalid status."
        }), 400

    updated = update_account_status(
        session["user_id"],
        account_id,
        status
    )

    if not updated:
        return jsonify({
            "error": "Account not found."
        }), 404

    return jsonify({
        "account_id": account_id,
        "status": status
    })


@api.route("/api/license/validate", methods=["POST"])
def validate_license_key():
    data = request.get_json(silent=True) or {}

    result = validate_license(data.get("license_key"))

    return jsonify(result), 200 if result["recognized"] else 400


@api.route("/api/bots/start", methods=["POST"])
def start_bot():
    try:
        session = require_authenticated_user(request)
    except PermissionError as error:
        return jsonify({
            "error": str(error)
        }), 401

    return jsonify({
        "error": "Bot starting is disabled until server-side license entitlement is connected."
    }), 503


@api.route("/api/bots/stop", methods=["POST"])
def stop_bot():
    try:
        session = require_authenticated_user(request)
    except PermissionError as error:
        return jsonify({
            "error": str(error)
        }), 401

    return jsonify({
        "error": "Bot stopping endpoint is not enabled yet."
    }), 503


@api.route("/api/commands/<uuid:command_id>", methods=["GET"])
def command_status(command_id):
    try:
        session = require_authenticated_user(request)
    except PermissionError as error:
        return jsonify({
            "error": str(error)
        }), 401

    command = get_command_status(
        session["user_id"],
        str(command_id)
    )

    if not command:
        return jsonify({
            "error": "Command not found."
        }), 404

    return jsonify(command)
