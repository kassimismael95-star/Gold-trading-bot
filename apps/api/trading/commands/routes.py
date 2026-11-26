
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify

from ...extensions import db
from ...models import TradingAccount, Command, AccountEvent
from ...security import agent_required


bp = Blueprint("agent", __name__, url_prefix="/api/agent")


@bp.post("/commands/next")
@agent_required
def next_command():
    data = request.get_json(silent=True) or {}
    agent_id = str(data.get("agent_id", ""))

    if agent_id != request.headers.get("X-Agent-ID", ""):
        return jsonify(error="agent_identity_mismatch"), 403

    account_id = data.get("account_id")

    query = (
        Command.query
        .join(TradingAccount)
        .filter(TradingAccount.agent_id == agent_id)
    )

    if account_id:
        query = query.filter(Command.account_id == int(account_id))

    stale_before = datetime.now(timezone.utc) - timedelta(minutes=2)

    stale_commands = query.filter(
        Command.status == "CLAIMED",
        Command.claimed_at < stale_before
    ).all()

    for command in stale_commands:
        command.status = "PENDING"
        command.claimed_at = None

    if stale_commands:
        db.session.flush()

    command = (
        query
        .filter(Command.status == "PENDING")
        .order_by(Command.id.asc())
        .with_for_update(skip_locked=True)
        .first()
    )

    if not command:
        db.session.commit()
        return jsonify(command=None)

    command.status = "CLAIMED"
    command.claimed_at = datetime.now(timezone.utc)

    db.session.commit()

    return jsonify(
        command={
            "id": command.id,
            "account_id": command.account_id,
            "command": command.command,
            "payload": command.payload
        }
    )


@bp.post("/events")
@agent_required
def events():
    data = request.get_json(silent=True) or {}

    account = db.session.get(
        TradingAccount,
        data.get("account_id")
    )

    if not account:
        return jsonify(error="account_not_found"), 404

    agent_id = request.headers.get("X-Agent-ID", "")

    if (
        account.agent_id != agent_id
        or account.agent_id != data.get("agent_id")
    ):
        return jsonify(error="account_agent_mismatch"), 403

    event_type = str(
        data.get("event_type", "telemetry")
    )[:40]

    payload = data.get("payload") or {}

    row = AccountEvent(
        account_id=account.id,
        event_type=event_type,
        payload=payload
    )

    db.session.add(row)

    if event_type == "status":
        account.actual_state = str(
            payload.get("state", "UNKNOWN")
        )[:20]

    db.session.commit()

    return jsonify(ok=True)
