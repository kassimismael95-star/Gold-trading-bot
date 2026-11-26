
"""Administrator merchant-balance, ledger and reconciliation endpoints."""
from flask import Blueprint, jsonify, current_app, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..extensions import db
from ..models import (
    User,
    Wallet,
    WalletBalanceSnapshot,
    WalletReconciliation,
)
from .wallet_service import ledger_totals

bp = Blueprint("wallet", __name__, url_prefix="/api/wallet")


def admin_user():
    try:
        user = User.query.get(int(get_jwt_identity()))
    except (TypeError, ValueError):
        return None

    return user if user and user.role == "admin" else None


@bp.get("/summary")
@jwt_required()
def summary():
    if not admin_user():
        return jsonify(error="admin_required"), 403

    snapshots = (
        WalletBalanceSnapshot.query
        .order_by(WalletBalanceSnapshot.checked_at.desc())
        .limit(1000)
        .all()
    )

    wallet_currency = {
        wallet.id: wallet.currency
        for wallet in Wallet.query.all()
    }

    latest = snapshots[0] if snapshots else None
    latest_currency = (
        wallet_currency.get(latest.wallet_id)
        if latest else None
    )

    latest_by_currency = {}

    for snapshot in snapshots:
        currency = wallet_currency.get(snapshot.wallet_id)

        if currency and currency not in latest_by_currency:
            latest_by_currency[currency] = {
                "currency": currency,
                "provider_balance": str(snapshot.provider_balance),
                "available_balance": str(snapshot.available_balance),
                "ledger_balance": str(snapshot.ledger_balance),
                "checked_at": snapshot.checked_at.isoformat(),
            }

    unmatched = WalletReconciliation.query.filter_by(
        status="UNMATCHED"
    ).count()

    return jsonify(
        **ledger_totals(),
        merchant_balance=(
            str(latest.provider_balance) if latest else None
        ),
        merchant_available_balance=(
            str(latest.available_balance) if latest else None
        ),
        merchant_balance_currency=latest_currency,
        merchant_balance_checked_at=(
            latest.checked_at.isoformat() if latest else None
        ),
        merchant_balances=list(latest_by_currency.values()),
        unmatched_reconciliations=unmatched,
    ), 200


@bp.post("/sync")
@jwt_required()
def sync_balance():
    if not admin_user():
        return jsonify(error="admin_required"), 403

    try:
        from .payment_scheduler import run_balance_sync

        snapshots = run_balance_sync(
            current_app._get_current_object()
        )

        wallets = {
            wallet.id: wallet.currency
            for wallet in Wallet.query.all()
        }

        return jsonify(
            ok=True,
            currencies=[
                wallets.get(snapshot.wallet_id)
                for snapshot in snapshots
            ],
            count=len(snapshots),
        ), 200

    except Exception:
        current_app.logger.exception(
            "merchant balance sync failed"
        )
        db.session.rollback()
        return jsonify(error="balance_sync_failed"), 502


@bp.get("/reconciliations")
@jwt_required()
def reconciliations():
    if not admin_user():
        return jsonify(error="forbidden"), 403

    rows = (
        WalletReconciliation.query
        .order_by(WalletReconciliation.id.desc())
        .limit(500)
        .all()
    )

    snapshot_ids = {
        row.snapshot_id
        for row in rows
        if row.snapshot_id
    }

    snapshots = (
        {
            row.id: row
            for row in WalletBalanceSnapshot.query.filter(
                WalletBalanceSnapshot.id.in_(snapshot_ids)
            ).all()
        }
        if snapshot_ids else {}
    )

    wallets = {
        wallet.id: wallet.currency
        for wallet in Wallet.query.all()
    }

    output = []

    for row in rows:
        snapshot = snapshots.get(row.snapshot_id)

        output.append({
            "id": row.id,
            "snapshot_id": row.snapshot_id,
            "currency": (
                wallets.get(snapshot.wallet_id)
                if snapshot else row.currency
            ),
            "provider": snapshot.provider if snapshot else None,
            "provider_balance": (
                str(snapshot.provider_balance)
                if snapshot else str(row.provider_balance)
            ),
            "available_balance": (
                str(snapshot.available_balance)
                if snapshot else None
            ),
            "ledger_balance": (
                str(snapshot.ledger_balance)
                if snapshot else str(row.ledger_balance)
            ),
            "difference": str(row.difference),
            "status": row.status,
            "note": row.note,
            "created_at": row.created_at.isoformat(),
        })

    return jsonify(reconciliations=output), 200


@bp.get("/snapshots")
@jwt_required()
def snapshots():
    if not admin_user():
        return jsonify(error="forbidden"), 403

    rows = (
        WalletBalanceSnapshot.query
        .order_by(WalletBalanceSnapshot.id.desc())
        .limit(500)
        .all()
    )

    wallets = {
        wallet.id: wallet.currency
        for wallet in Wallet.query.all()
    }

    return jsonify(
        snapshots=[
            {
                "id": row.id,
                "wallet_id": row.wallet_id,
                "currency": wallets.get(row.wallet_id),
                "provider": row.provider,
                "provider_balance": str(row.provider_balance),
                "available_balance": str(row.available_balance),
                "ledger_balance": str(row.ledger_balance),
                "checked_at": row.checked_at.isoformat(),
            }
            for row in rows
        ]
    ), 200


@bp.post("/reconciliations/<int:reconciliation_id>/resolve")
@jwt_required()
def resolve_reconciliation(reconciliation_id):
    actor = admin_user()

    if not actor:
        return jsonify(error="forbidden"), 403

    row = WalletReconciliation.query.get(
        reconciliation_id
    )

    if not row:
        return jsonify(error="reconciliation_not_found"), 404

    data = request.get_json(silent=True) or {}
    note = str(data.get("note", "")).strip()

    if len(note) < 5 or len(note) > 500:
        return jsonify(
            error="resolution_note_must_be_5_to_500_chars"
        ), 400

    row.status = "RESOLVED"
    row.note = (
        (row.note or "") + " | Resolution: " + note
    )[-500:]

    from ..security.audit_service import record_audit

    record_audit(
        "wallet.reconciliation.resolved",
        actor.id,
        "wallet_reconciliation",
        row.id,
        {"note": note},
        request.remote_addr,
    )

    db.session.commit()

    return jsonify(
        ok=True,
        reconciliation_id=row.id,
        status=row.status,
    ), 200
