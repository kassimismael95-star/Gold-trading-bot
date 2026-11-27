
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    TradingAccount,
    Command,
    AccountEvent,
    AccountTelemetry,
)

bp = Blueprint("ea", __name__, url_prefix="/api/ea")


def utcnow():
    return datetime.now(timezone.utc)


def get_account(account_id):
    if not account_id:
        return None

    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        return None

    return db.session.get(TradingAccount, account_id)


def authorized(account):
    if account is None:
        return False

    supplied = request.headers.get("X-EA-Token", "").strip()

    if not supplied or not account.ea_token_hash:
        return False

    candidate = hashlib.sha256(
        supplied.encode("utf-8")
    ).hexdigest()

    return hmac.compare_digest(
        candidate,
        account.ea_token_hash
    )


def json_body():
    data = request.get_json(silent=True)

    return data if isinstance(data, dict) else {}


def permission_result(account):
    """
    Fail-closed entry permission.

    Demo accounts still require the normal account, licence and
    desired-state checks.

    Live accounts additionally require the global server switch.

    This endpoint does not override the EA's own live-trading
    confirmation inputs.
    """

    mode = str(account.mode or "").strip().lower()

    live_enabled = bool(
        current_app.config.get("ALLOW_LIVE_TRADING", False)
    )

    if account.is_deleted:
        return False, "account_removed"

    if mode not in ("demo", "live"):
        return False, "invalid_account_mode"

    if mode == "live" and not live_enabled:
        return False, "live_trading_disabled_on_server"

    if account.desired_state != "RUNNING":
        return False, "account_not_running"

    try:
        from ..licences.service import can_start_new_entries

        entitled = can_start_new_entries(account.owner_id)

    except Exception:
        current_app.logger.exception(
            "EA licence permission check failed"
        )
        db.session.rollback()
        return False, "licence_check_failed"

    if not entitled:
        return False, "licence_or_subscription_required"

    return True, "authorized"


@bp.get("/next")
def next_command():
    account_id = request.args.get("account_id", type=int)
    account = get_account(account_id)

    if not account or not authorized(account):
        return jsonify(error="unauthorized"), 401

    # An EA that temporarily disconnects must be able to receive
    # its command again after an abandoned claim expires.
    stale_before = utcnow() - timedelta(minutes=2)

    stale_commands = Command.query.filter_by(
        account_id=account.id,
        status="CLAIMED"
    ).filter(
        Command.claimed_at < stale_before
    ).all()

    for item in stale_commands:
        item.status = "PENDING"
        item.claimed_at = None

    if stale_commands:
        db.session.flush()

    row = (
        Command.query
        .filter_by(
            account_id=account.id,
            status="PENDING"
        )
        .order_by(Command.id.asc())
        .with_for_update(skip_locked=True)
        .first()
    )

    if row is None:
        db.session.commit()
        return jsonify(command=None), 200

    row.status = "CLAIMED"
    row.claimed_at = utcnow()

    db.session.commit()

    return jsonify(
        command={
            "id": row.id,
            "command": row.command,
            "payload": row.payload or {}
        }
    ), 200


@bp.post("/events")
def event():
    data = json_body()

    account = get_account(data.get("account_id"))

    if not account or not authorized(account):
        return jsonify(error="unauthorized"), 401

    kind = str(
        data.get("event_type", "telemetry")
    ).strip()[:40]

    payload = data.get("payload") or {}

    if not isinstance(payload, dict):
        return jsonify(
            error="event_payload_must_be_object"
        ), 400

    if kind == "heartbeat":
        account.last_seen = utcnow()

        row = AccountTelemetry.query.filter_by(
            account_id=account.id
        ).first()

        if row is None:
            row = AccountTelemetry(
                account_id=account.id
            )

        amounts = {}

        for field in (
            "balance",
            "equity",
            "free_margin",
            "floating_pnl"
        ):
            try:
                value = Decimal(
                    str(payload.get(field, 0) or 0)
                )
            except (
                InvalidOperation,
                TypeError,
                ValueError
            ):
                return jsonify(
                    error="invalid_heartbeat_telemetry",
                    field=field
                ), 400

            if not value.is_finite():
                return jsonify(
                    error="invalid_heartbeat_telemetry",
                    field=field
                ), 400

            amounts[field] = value

        try:
            positions = int(
                payload.get("open_positions_count", 0) or 0
            )
        except (TypeError, ValueError):
            return jsonify(
                error="invalid_heartbeat_telemetry",
                field="open_positions_count"
            ), 400

        entries_enabled = payload.get(
            "entries_enabled", False
        )

        connected = payload.get(
            "connected_to_broker", False
        )

        if (
            not isinstance(entries_enabled, bool)
            or not isinstance(connected, bool)
            or positions < 0
            or positions > 1000
        ):
            return jsonify(
                error="invalid_heartbeat_telemetry"
            ), 400

        row.balance = amounts["balance"]
        row.equity = amounts["equity"]
        row.free_margin = amounts["free_margin"]
        row.floating_pnl = amounts["floating_pnl"]

        row.open_positions_count = positions
        row.active_symbol = str(
            payload.get("symbol", "")
        )[:40]

        row.entries_enabled = entries_enabled
        row.connected_to_broker = connected
        row.updated_at = utcnow()

        account.actual_state = (
            "CONNECTED" if connected else "DISCONNECTED"
        )

        db.session.add(row)

    else:
        event_key = None

        if (
            kind == "trade_deal"
            and str(payload.get("deal_id", "")).isdigit()
        ):
            event_key = (
                f"{account.id}:deal:{payload.get('deal_id')}"
            )

            existing = AccountEvent.query.filter_by(
                event_key=event_key
            ).first()

            if existing:
                return jsonify(
                    ok=True,
                    duplicate=True
                ), 200

        row = AccountEvent(
            account_id=account.id,
            event_type=kind,
            payload=payload,
            event_key=event_key
        )

        db.session.add(row)

    if kind == "status":
        state = str(
            payload.get("state", "UNKNOWN")
        ).strip().upper()

        account.actual_state = state[:20]

    db.session.commit()

    return jsonify(ok=True), 200


@bp.post("/ack")
def acknowledge_command():
    data = json_body()

    account = get_account(data.get("account_id"))

    if not account or not authorized(account):
        return jsonify(error="unauthorized"), 401

    try:
        command_id = int(data.get("command_id"))
    except (TypeError, ValueError):
        return jsonify(
            error="invalid_command_id"
        ), 400

    row = Command.query.filter_by(
        id=command_id,
        account_id=account.id
    ).first()

    if row is None:
        return jsonify(
            error="command_not_found"
        ), 404

    if row.status == "DONE":
        return jsonify(
            ok=True,
            duplicate=True
        ), 200

    if row.status != "CLAIMED":
        return jsonify(
            error="command_not_claimed"
        ), 409

    result = data.get("result")

    if not isinstance(result, dict):
        result = {}

    row.status = "DONE"
    row.completed_at = utcnow()
    row.result = result

    db.session.commit()

    return jsonify(
        ok=True,
        status=row.status
    ), 200


@bp.get("/permission")
def permission():
    account_id = request.args.get("account_id", type=int)
    account = get_account(account_id)

    if not account or not authorized(account):
        return jsonify(error="unauthorized"), 401

    allowed, reason = permission_result(account)

    return jsonify(
        entries_allowed=bool(allowed),
        reason=reason,
        desired_state=account.desired_state,
        mode=account.mode,
        is_deleted=bool(account.is_deleted),
        server_live_trading_enabled=bool(
            current_app.config.get(
                "ALLOW_LIVE_TRADING",
                False
            )
        )
    ), 200


@bp.post("/deals/batch")
def deals_batch():
    data = json_body()

    account = get_account(data.get("account_id"))

    if not account or not authorized(account):
        return jsonify(error="unauthorized"), 401

    deals = data.get("deals")

    if not isinstance(deals, list) or len(deals) > 1000:
        return jsonify(
            error="deals_must_be_array_max_1000"
        ), 400

    normalized = []
    keys = []
    seen = set()
    duplicates = 0

    for item in deals:
        if not isinstance(item, dict):
            return jsonify(
                error="invalid_deal_record"
            ), 400

        deal_id = str(item.get("deal_id", ""))

        if not deal_id.isdigit() or len(deal_id) > 32:
            return jsonify(
                error="invalid_deal_id"
            ), 400

        key = f"{account.id}:deal:{deal_id}"

        if key in seen:
            duplicates += 1
            continue

        seen.add(key)
        keys.append(key)

        try:
            volume = Decimal(
                str(item.get("volume", 0))
            )

            profit = Decimal(
                str(item.get("profit", 0))
            )

            magic = int(item.get("magic", 0))
            entry = int(item.get("entry", 0))
            deal_time = int(item.get("time", 0))

        except (
            InvalidOperation,
            TypeError,
            ValueError
        ):
            return jsonify(
                error="invalid_deal_values"
            ), 400

        if (
            not volume.is_finite()
            or not profit.is_finite()
            or volume < 0
            or abs(profit) > Decimal("1000000000")
        ):
            return jsonify(
                error="invalid_deal_values"
            ), 400

        side = str(
            item.get("side", "OTHER")
        ).upper()

        if side not in {"BUY", "SELL", "OTHER"}:
            return jsonify(
                error="invalid_deal_side"
            ), 400

        symbol = str(
            item.get("symbol", "")
        )[:40]

        normalized.append((
            key,
            {
                "deal_id": deal_id,
                "magic": magic,
                "symbol": symbol,
                "side": side,
                "volume": str(volume),
                "profit": str(profit),
                "entry": entry,
                "time": deal_time
            }
        ))

    existing = set()

    if keys:
        existing = set(
            row[0]
            for row in AccountEvent.query.filter(
                AccountEvent.event_key.in_(keys)
            ).with_entities(
                AccountEvent.event_key
            ).all()
        )

    rows = []

    for key, payload in normalized:
        if key in existing:
            duplicates += 1
            continue

        rows.append(
            AccountEvent(
                account_id=account.id,
                event_type="trade_deal",
                payload=payload,
                event_key=key
            )
        )

    try:
        if rows:
            db.session.add_all(rows)
            db.session.commit()

    except IntegrityError:
        db.session.rollback()

        # A concurrent duplicate upload is safe only if all
        # submitted deal identifiers now exist.
        missing = [
            key
            for key, _ in normalized
            if not AccountEvent.query.filter_by(
                event_key=key
            ).first()
        ]

        if missing:
            return jsonify(
                error="batch_conflict_retry"
            ), 409

        return jsonify(
            ok=True,
            duplicate=True
        ), 200

    return jsonify(
        ok=True,
        inserted=len(rows),
        duplicates=duplicates
    ), 200
