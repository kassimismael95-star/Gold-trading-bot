
"""Authenticated Oracle agent assignment and credential-delivery endpoints.

Credentials are decrypted only for an agent assigned to the account.
Never log responses from /credentials and always use HTTPS outside
local development.
"""

import hashlib
import hmac
import math
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, current_app

# These modules are in apps/api/, one directory above this file.
from ..extensions import db
from ..models import Agent, TradingAccount, AccountCredential, AccountTelemetry


bp = Blueprint("agent_control", __name__, url_prefix="/api/agent")


def _bootstrap_authorized():
    supplied = request.headers.get("X-Agent-Secret", "")
    expected = str(current_app.config.get("AGENT_SHARED_SECRET", ""))

    return bool(
        expected
        and supplied
        and hmac.compare_digest(supplied, expected)
    )


def _authorized():
    agent_id = request.headers.get("X-Agent-ID", "").strip()[:80]
    supplied = request.headers.get("X-Agent-Secret", "")

    if not agent_id or not supplied:
        return False

    agent = Agent.query.filter_by(agent_id=agent_id).first()

    if not agent or not agent.secret_hash:
        return False

    candidate = hashlib.sha256(supplied.encode()).hexdigest()

    return hmac.compare_digest(candidate, agent.secret_hash)


@bp.before_request
def require_agent_secret():
    # The shared bootstrap secret is accepted only during enrollment.
    if request.endpoint == "agent_control.register_agent":
        if not _bootstrap_authorized():
            return jsonify(error="agent_bootstrap_unauthorized"), 401
        return None

    if not _authorized():
        return jsonify(error="agent_unauthorized"), 401


@bp.post("/register")
def register_agent():
    data = request.get_json(silent=True) or {}

    if not isinstance(data, dict):
        return jsonify(error="invalid_json_object"), 400

    agent_id = str(data.get("agent_id", "")).strip()[:80]

    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", agent_id):
        return jsonify(error="valid_agent_id_required"), 400

    row = Agent.query.filter_by(agent_id=agent_id).first()

    if row and row.secret_hash:
        return jsonify(
            error="agent_already_enrolled_contact_admin_for_rotation"
        ), 409

    if row is None:
        row = Agent(agent_id=agent_id)

    secret = secrets.token_urlsafe(48)

    row.secret_hash = hashlib.sha256(secret.encode()).hexdigest()
    row.hostname = str(data.get("hostname", ""))[:120]
    row.status = "ONLINE"
    row.last_seen = datetime.now(timezone.utc)

    db.session.add(row)
    db.session.commit()

    return jsonify(
        agent_id=agent_id,
        agent_secret=secret,
        notice="Store this secret securely; it is shown only once."
    ), 201


@bp.post("/heartbeat")
def heartbeat():
    data = request.get_json(silent=True) or {}

    if not isinstance(data, dict):
        return jsonify(error="invalid_json_object"), 400

    agent_id = str(data.get("agent_id", "")).strip()[:80]

    if not agent_id:
        return jsonify(error="agent_id_required"), 400

    if agent_id != request.headers.get("X-Agent-ID", ""):
        return jsonify(error="agent_identity_mismatch"), 403

    row = Agent.query.filter_by(agent_id=agent_id).first()

    if row is None:
        return jsonify(error="agent_not_registered"), 404

    row.hostname = str(data.get("hostname", ""))[:120]

    metrics = data.get("metrics") or {}

    if not isinstance(metrics, dict):
        return jsonify(error="metrics_must_be_object"), 400

    allowed = {
        "cpu_count",
        "cpu_percent",
        "memory_total_bytes",
        "memory_available_bytes",
        "memory_percent",
        "process_count",
        "disk_free_bytes",
        "recommended_capacity",
    }

    integer_keys = {
        "cpu_count",
        "memory_total_bytes",
        "memory_available_bytes",
        "process_count",
        "disk_free_bytes",
        "recommended_capacity",
    }

    safe = {}

    for key, value in metrics.items():
        if key not in allowed:
            continue

        try:
            number = float(value)
        except (TypeError, ValueError):
            return jsonify(error="invalid_agent_metric", key=key), 400

        if not math.isfinite(number) or number < 0:
            return jsonify(error="invalid_agent_metric", key=key), 400

        if key in integer_keys and int(number) != number:
            return jsonify(error="invalid_agent_metric", key=key), 400

        if key == "recommended_capacity" and not 1 <= number <= 1000:
            return jsonify(error="invalid_agent_metric", key=key), 400

        safe[key] = int(number) if key in integer_keys else number

    row.metrics = safe
    row.status = "ONLINE"
    row.last_seen = datetime.now(timezone.utc)

    db.session.add(row)
    db.session.commit()

    return jsonify(ok=True, agent_id=agent_id)


@bp.get("/accounts")
def assigned_accounts():
    agent_id = str(request.args.get("agent_id", "")).strip()[:80]

    if not agent_id:
        return jsonify(error="agent_id_required"), 400

    if agent_id != request.headers.get("X-Agent-ID", ""):
        return jsonify(error="agent_identity_mismatch"), 403

    agent = Agent.query.filter_by(
        agent_id=agent_id,
        status="ONLINE"
    ).first()

    if not agent:
        return jsonify(error="agent_not_registered"), 409

    now = datetime.now(timezone.utc)

    assigned_rows = TradingAccount.query.filter_by(
        agent_id=agent_id
    ).all()

    rows = []
    cleanup_ids = []

    # Deleted accounts remain assigned until a recent EA telemetry
    # update confirms that the broker has no open positions.
    for account in assigned_rows:
        if account.is_deleted:
            telemetry = AccountTelemetry.query.filter_by(
                account_id=account.id
            ).first()

            recent = False

            if telemetry and telemetry.updated_at:
                updated = telemetry.updated_at

                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)

                recent = (
                    timedelta(0) <= now - updated <= timedelta(seconds=90)
                )

            if (
                telemetry
                and recent
                and telemetry.connected_to_broker
                and telemetry.open_positions_count == 0
            ):
                account.agent_id = None
                account.actual_state = "REMOVED"
                cleanup_ids.append(account.id)

                credential = AccountCredential.query.filter_by(
                    account_id=account.id
                ).first()

                if credential:
                    credential.revoked = True
                    credential.version += 1

                account.ea_token_hash = hashlib.sha256(
                    secrets.token_urlsafe(32).encode()
                ).hexdigest()

                account.ea_token_ciphertext = None
                account.ea_token_version += 1

                continue

        rows.append(account)

    if cleanup_ids:
        from ..security.audit_service import record_audit

        for removed_id in cleanup_ids:
            record_audit(
                "account.removal.completed",
                None,
                "account",
                removed_id,
                {"agent_id": agent_id},
                None
            )

        db.session.commit()

    assigned_count = len(rows)

    configured = max(1, int(agent.capacity or 20))

    resource_cap = int(
        (agent.metrics or {}).get("recommended_capacity", 0) or 0
    )

    effective_capacity = (
        min(configured, resource_cap)
        if resource_cap > 0
        else configured
    )

    available = max(0, effective_capacity - assigned_count)

    pending = []

    if available > 0:
        pending = (
            TradingAccount.query
            .filter(
                TradingAccount.agent_id.is_(None),
                TradingAccount.is_deleted.is_(False)
            )
            .order_by(TradingAccount.id)
            .with_for_update(skip_locked=True)
            .limit(min(10, available))
            .all()
        )

        for account in pending:
            account.agent_id = agent_id

        if pending:
            db.session.commit()

    rows.extend(pending)
    assigned_count = len(rows)

    accounts = []

    for account in rows:
        credential = AccountCredential.query.filter_by(
            account_id=account.id
        ).first()

        accounts.append({
            "id": account.id,
            "login": account.login,
            "server": account.server,
            "broker": account.broker,
            "mode": account.mode,
            "symbol": account.symbol,
            "desired_state": account.desired_state,
            "ea_token_hash": account.ea_token_hash,
            "ea_token_version": account.ea_token_version,
            "credential_version": credential.version if credential else 0,
            "risk_settings": account.risk_settings or {},
            "live_trading_allowed": bool(
                account.mode == "live"
                and current_app.config.get("ALLOW_LIVE_TRADING", False)
            ),
            "credential_ready": bool(
                credential and not credential.revoked
            ),
            "is_deleted": account.is_deleted,
            "agent_capacity": effective_capacity,
            "agent_assigned_count": assigned_count,
        })

    return jsonify(accounts=accounts)


@bp.get("/accounts/<int:account_id>/credentials")
def account_credentials(account_id):
    agent_id = request.headers.get("X-Agent-ID", "").strip()[:80]

    requested_agent_id = request.args.get("agent_id")

    if requested_agent_id and str(requested_agent_id) != agent_id:
        return jsonify(error="agent_identity_mismatch"), 403

    account = TradingAccount.query.filter_by(
        id=account_id,
        agent_id=agent_id
    ).first()

    if not account:
        return jsonify(error="account_not_assigned_to_agent"), 403

    credential = AccountCredential.query.filter_by(
        account_id=account_id,
        revoked=False
    ).first()

    if not credential:
        return jsonify(error="credential_missing_or_revoked"), 404

    # These security modules are in apps/api/security/.
    from ..security.credential_vault import (
        open_mt5_password,
        seal_mt5_password
    )
    from ..security.encryption import decrypt_secret, encrypt_secret

    try:
        from cryptography.exceptions import InvalidTag

        try:
            password = open_mt5_password(
                credential.password_ciphertext,
                account.id
            )
        except InvalidTag:
            # Upgrade legacy unbound ciphertext after authenticated retrieval.
            password = open_mt5_password(
                credential.password_ciphertext
            )
            credential.password_ciphertext = seal_mt5_password(
                password,
                account.id
            )

        try:
            ea_token = (
                decrypt_secret(
                    account.ea_token_ciphertext,
                    f"ea-token:{account.id}"
                )
                if account.ea_token_ciphertext
                else None
            )
        except InvalidTag:
            ea_token = decrypt_secret(account.ea_token_ciphertext)
            account.ea_token_ciphertext = encrypt_secret(
                ea_token,
                f"ea-token:{account.id}"
            )

        db.session.commit()

    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "credential decrypt failed for account_id=%s",
            account_id
        )
        return jsonify(error="credential_unavailable"), 503

    # Secret-bearing response: never log its contents.
    return jsonify(
        account_id=account.id,
        login=account.login,
        server=account.server,
        password=password,
        ea_token=ea_token,
        credential_version=credential.version
    )
