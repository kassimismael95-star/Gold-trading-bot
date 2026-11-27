
import hashlib
import re
import secrets

from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required

from ..extensions import db
from ..models import (
    TradingAccount,
    Command,
    AccountEvent,
    AccountCredential,
)
from ..security import current_user, owner_account
from ..licences.service import can_start_new_entries


bp = Blueprint("accounts", __name__, url_prefix="/api/accounts")


def live_trading_allowed():
    return bool(current_app.config.get("ALLOW_LIVE_TRADING", False))


@bp.get("")
@jwt_required()
def list_accounts():
    user = current_user()

    rows = TradingAccount.query.filter_by(
        owner_id=user.id
    ).all()

    from ..models import AccountTelemetry

    telemetry = {}

    if rows:
        telemetry = {
            t.account_id: t
            for t in AccountTelemetry.query.filter(
                AccountTelemetry.account_id.in_(
                    [x.id for x in rows]
                )
            ).all()
        }

    return jsonify(
        accounts=[
            serialize(account, telemetry.get(account.id))
            for account in rows
        ]
    )


@bp.post("")
@jwt_required()
def create_account():
    user = current_user()
    data = request.get_json(silent=True) or {}

    required = (
        "label",
        "login",
        "server",
        "mt5_password",
    )

    if any(
        not str(data.get(key, "")).strip()
        for key in required
    ):
        return jsonify(
            error="label_login_server_and_mt5_password_required"
        ), 400

    login = str(data["login"]).strip()
    server = str(data["server"]).strip()
    label = str(data["label"]).strip()
    symbol = str(data.get("symbol", "AUTO")).strip()
    broker = str(data.get("broker", "Exness")).strip()

    if not login.isdigit() or len(login) > 40:
        return jsonify(
            error="mt5_login_must_be_numeric"
        ), 400

    if not re.fullmatch(
        r"[A-Za-z0-9 ._-]{1,120}",
        server
    ):
        return jsonify(
            error="valid_mt5_server_required"
        ), 400

    if not re.fullmatch(
        r"AUTO|[A-Za-z0-9._-]{1,40}",
        symbol
    ):
        return jsonify(
            error="valid_mt5_symbol_required"
        ), 400

    if not label or len(label) > 80:
        return jsonify(
            error="valid_account_label_required"
        ), 400

    if not broker or len(broker) > 80:
        return jsonify(
            error="valid_broker_required"
        ), 400

    mode = str(data.get("mode", "demo")).strip().lower()

    if mode not in ("demo", "live"):
        return jsonify(
            error="mode_must_be_demo_or_live"
        ), 400

    if mode == "live" and not live_trading_allowed():
        return jsonify(
            error="live_trading_disabled_by_server"
        ), 403

    password = str(data.get("mt5_password", ""))

    if (
        not password
        or len(password) > 512
        or "\r" in password
        or "\n" in password
    ):
        return jsonify(
            error="valid_mt5_password_required"
        ), 400

    from ..security.credential_vault import (
        seal_mt5_password
    )
    from ..security.encryption import encrypt_secret

    ea_token = secrets.token_urlsafe(32)

    account = TradingAccount(
        owner_id=user.id,
        label=label,
        login=login,
        server=server,
        broker=broker,
        mode=mode,
        symbol=symbol,
        agent_id=None,
        desired_state="STOPPED",
        ea_token_hash=hashlib.sha256(
            ea_token.encode()
        ).hexdigest(),
    )

    db.session.add(account)
    db.session.flush()

    account.ea_token_ciphertext = encrypt_secret(
        ea_token,
        f"ea-token:{account.id}",
    )

    credential = AccountCredential(
        account_id=account.id,
        password_ciphertext=seal_mt5_password(
            password,
            account.id,
        ),
    )

    db.session.add(credential)

    from ..security.audit_service import record_audit

    record_audit(
        "account.created",
        user.id,
        "account",
        account.id,
        {
            "mode": mode,
            "broker": broker,
        },
        request.remote_addr,
    )

    db.session.commit()

    return jsonify(
        account=serialize(account),
        ea_token=ea_token,
        ea_token_notice=(
            "Copy this token into the EA input. "
            "It is shown only once."
        ),
    ), 201


@bp.post("/<int:account_id>/ea-token/regenerate")
@jwt_required()
@owner_account
def regenerate_ea_token(account):
    ea_token = secrets.token_urlsafe(32)

    from ..security.encryption import encrypt_secret

    account.ea_token_hash = hashlib.sha256(
        ea_token.encode()
    ).hexdigest()

    account.ea_token_ciphertext = encrypt_secret(
        ea_token,
        f"ea-token:{account.id}",
    )

    account.ea_token_version = (
        account.ea_token_version or 0
    ) + 1

    account.desired_state = "STOPPED"

    from ..security.audit_service import record_audit

    record_audit(
        "account.ea_token.rotated",
        current_user().id,
        "account",
        account.id,
        {},
        request.remote_addr,
    )

    db.session.commit()

    return jsonify(
        ea_token=ea_token,
        notice=(
            "Old EA token is invalid. "
            "Copy the new token into the EA input."
        ),
    ), 200


@bp.get("/<int:account_id>/status")
@jwt_required()
@owner_account
def status(account):
    events = (
        AccountEvent.query
        .filter_by(account_id=account.id)
        .order_by(AccountEvent.id.desc())
        .limit(10)
        .all()
    )

    return jsonify(
        account=serialize(account),
        events=[
            {
                "type": event.event_type,
                "payload": event.payload,
                "at": event.created_at.isoformat(),
            }
            for event in events
        ],
    )


@bp.post("/<int:account_id>/commands")
@jwt_required()
@owner_account
def command(account):
    data = request.get_json(silent=True) or {}

    name = str(
        data.get("command", "")
    ).strip().upper()

    supported_commands = {
        "START",
        "STOP",
        "CLOSE_ALL",
        "SETTINGS",
        "EMERGENCY_STOP",
        "EMERGENCY_RESET",
    }

    if name not in supported_commands:
        return jsonify(
            error="unsupported_command"
        ), 400

    if account.is_deleted:
        return jsonify(
            error="account_is_being_removed"
        ), 409

    payload = data.get("payload") or {}

    if not isinstance(payload, dict):
        return jsonify(
            error="command_payload_must_be_object"
        ), 400

    if name == "START":
        if account.mode == "live" and not live_trading_allowed():
            return jsonify(
                error="live_trading_disabled_by_server"
            ), 403

        if not can_start_new_entries(account.owner_id):
            return jsonify(
                error="active_licence_or_subscription_required"
            ), 403

    if name == "EMERGENCY_RESET":
        pending_close = Command.query.filter(
            Command.account_id == account.id,
            Command.command == "CLOSE_ALL",
            Command.status.in_(("PENDING", "CLAIMED")),
        ).first()

        if pending_close:
            return jsonify(
                error="close_all_command_still_pending"
            ), 409

        # Resetting the emergency latch never starts trading.
        account.desired_state = "STOPPED"

    if name == "SETTINGS":
        allowed = {
            "max_positions",
            "one_entry_per_m1_bar",
        }

        unsupported = set(payload.keys()) - allowed

        if unsupported:
            return jsonify(
                error="unsupported_setting_for_current_ea",
                keys=sorted(unsupported),
                supported=sorted(allowed),
            ), 400

        current = {
            "max_positions": 0,
            "one_entry_per_m1_bar": False,
        }

        previous = account.risk_settings or {}

        if isinstance(previous, dict):
            if "max_positions" in previous:
                current["max_positions"] = previous[
                    "max_positions"
                ]

            if "one_entry_per_m1_bar" in previous:
                current["one_entry_per_m1_bar"] = previous[
                    "one_entry_per_m1_bar"
                ]

        if "max_positions" in payload:
            value = payload["max_positions"]

            if isinstance(value, bool):
                return jsonify(
                    error="integer_setting_required",
                    key="max_positions",
                ), 400

            try:
                number = float(value)
            except (TypeError, ValueError):
                return jsonify(
                    error="invalid_setting_value",
                    key="max_positions",
                ), 400

            if (
                not number.is_integer()
                or number < 0
                or number > 18
            ):
                return jsonify(
                    error="setting_out_of_range",
                    key="max_positions",
                    min=0,
                    max=18,
                ), 400

            current["max_positions"] = int(number)

        if "one_entry_per_m1_bar" in payload:
            value = payload["one_entry_per_m1_bar"]

            if not isinstance(value, bool):
                return jsonify(
                    error="boolean_setting_required",
                    key="one_entry_per_m1_bar",
                ), 400

            current["one_entry_per_m1_bar"] = value

        account.risk_settings = current
        payload = current

    if name == "START":
        account.desired_state = "RUNNING"

    elif name in (
        "STOP",
        "CLOSE_ALL",
        "EMERGENCY_STOP",
        "EMERGENCY_RESET",
    ):
        account.desired_state = "STOPPED"

    if name == "EMERGENCY_STOP":
        payload = {
            **payload,
            "policy": "STOP_NEW_ENTRIES_MANAGE_EXISTING",
        }

    row = Command(
        account_id=account.id,
        command=name,
        payload=payload,
    )

    db.session.add(row)

    from ..security.audit_service import record_audit

    record_audit(
        "account.command.queued",
        current_user().id,
        "account",
        account.id,
        {
            "command": name,
        },
        request.remote_addr,
    )

    db.session.commit()

    return jsonify(
        command_id=row.id,
        status=row.status,
        desired_state=account.desired_state,
    ), 202


@bp.put("/<int:account_id>/credentials")
@jwt_required()
@owner_account
def update_credentials(account):
    data = request.get_json(silent=True) or {}
    password = str(data.get("mt5_password", ""))

    if (
        not password
        or len(password) > 512
        or "\r" in password
        or "\n" in password
    ):
        return jsonify(
            error="valid_mt5_password_required"
        ), 400

    from ..security.credential_vault import (
        seal_mt5_password
    )

    row = AccountCredential.query.filter_by(
        account_id=account.id
    ).first()

    if row is None:
        row = AccountCredential(
            account_id=account.id,
            password_ciphertext=seal_mt5_password(
                password,
                account.id,
            ),
        )
    else:
        row.password_ciphertext = seal_mt5_password(
            password,
            account.id,
        )
        row.version += 1
        row.revoked = False

    account.desired_state = "STOPPED"

    db.session.add(row)

    from ..security.audit_service import record_audit

    record_audit(
        "account.credentials.updated",
        current_user().id,
        "account",
        account.id,
        {
            "credential_version": row.version,
        },
        request.remote_addr,
    )

    db.session.commit()

    return jsonify(
        ok=True,
        credential_version=row.version,
    )


@bp.delete("/<int:account_id>/credentials")
@jwt_required()
@owner_account
def revoke_credentials(account):
    row = AccountCredential.query.filter_by(
        account_id=account.id
    ).first()

    if row:
        row.revoked = True
        row.version += 1
        account.desired_state = "STOPPED"

        from ..security.audit_service import record_audit

        record_audit(
            "account.credentials.revoked",
            current_user().id,
            "account",
            account.id,
            {},
            request.remote_addr,
        )

        db.session.commit()

    return jsonify(
        ok=True,
        revoked=True,
    )


def serialize(account, telemetry=None):
    actual = (
        "REMOVED"
        if account.is_deleted and account.agent_id is None
        else account.actual_state
    )

    if (
        account.last_seen
        and not (
            account.is_deleted
            and account.agent_id is None
        )
    ):
        seen = account.last_seen

        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)

        if (
            datetime.now(timezone.utc) - seen
            > timedelta(seconds=90)
        ):
            actual = "STALE"

    live = None

    if telemetry:
        live = {
            "balance": str(telemetry.balance),
            "equity": str(telemetry.equity),
            "free_margin": str(telemetry.free_margin),
            "floating_pnl": str(telemetry.floating_pnl),
            "open_positions_count": telemetry.open_positions_count,
            "active_symbol": telemetry.active_symbol,
            "entries_enabled": telemetry.entries_enabled,
            "connected_to_broker": telemetry.connected_to_broker,
            "updated_at": telemetry.updated_at.isoformat(),
        }

    return {
        "id": account.id,
        "label": account.label,
        "broker": account.broker,
        "login": account.login,
        "server": account.server,
        "mode": account.mode,
        "symbol": account.symbol,
        "desired_state": account.desired_state,
        "actual_state": actual,
        "agent_id": account.agent_id,
        "is_deleted": account.is_deleted,
        "risk_settings": account.risk_settings or {},
        "telemetry": live,
        "last_seen": (
            account.last_seen.isoformat()
            if account.last_seen
            else None
        ),
    }


@bp.delete("/<int:account_id>")
@jwt_required()
def delete_account(account_id):
    user = current_user()

    account = TradingAccount.query.filter_by(
        id=account_id,
        owner_id=user.id,
    ).first()

    if not account:
        return jsonify(
            error="account_not_found"
        ), 404

    if account.is_deleted:
        return jsonify(
            ok=True,
            removal_pending=bool(account.agent_id),
            status=(
                "REMOVING"
                if account.agent_id
                else "REMOVED"
            ),
        ), 200

    from ..models import AccountTelemetry

    telemetry = AccountTelemetry.query.filter_by(
        account_id=account.id
    ).first()

    recent = False

    if telemetry and telemetry.updated_at:
        updated = telemetry.updated_at

        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)

        recent = (
            datetime.now(timezone.utc) - updated
            <= timedelta(seconds=90)
        )

    can_detach = (
        account.agent_id is None
        or (
            telemetry is not None
            and recent
            and telemetry.connected_to_broker
            and telemetry.open_positions_count == 0
        )
    )

    account.is_deleted = True
    account.desired_state = "STOPPED"

    if can_detach:
        account.agent_id = None
        account.actual_state = "REMOVED"

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

    from ..security.audit_service import record_audit

    record_audit(
        "account.removal.requested",
        user.id,
        "account",
        account.id,
        {
            "detached": bool(can_detach),
            "open_positions": (
                telemetry.open_positions_count
                if telemetry
                else None
            ),
        },
        request.remote_addr,
    )

    if can_detach:
        record_audit(
            "account.removal.completed",
            user.id,
            "account",
            account.id,
            {},
            request.remote_addr,
        )

    db.session.commit()

    return jsonify(
        ok=True,
        removal_pending=bool(account.agent_id),
        status=(
            "REMOVING"
            if account.agent_id
            else "REMOVED"
        ),
        open_positions=(
            telemetry.open_positions_count
            if telemetry
            else None
        ),
    ), 202
