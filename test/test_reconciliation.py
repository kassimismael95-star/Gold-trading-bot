import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from execution.reconciliation import ReconciliationService


@pytest.fixture
def database():
    database = MagicMock()

    database.get_account.return_value = {
        "id": "account-1",
        "worker_id": "worker-1",
        "last_position_update_at": datetime.now(timezone.utc).isoformat(),
    }

    database.get_pending_commands.return_value = []

    return database


@pytest.fixture
def worker_registry():
    worker_registry = MagicMock()

    worker_registry.get_worker.return_value = {
        "id": "worker-1",
        "status": "ACTIVE",
    }

    return worker_registry


@pytest.fixture
def reconciliation(database, worker_registry):
    return ReconciliationService(
        database=database,
        worker_registry=worker_registry,
    )


def test_account_not_found(reconciliation, database):
    database.get_account.return_value = None

    result = asyncio.run(
        reconciliation.reconcile_account("missing-account")
    )

    assert result.action_taken == "ACCOUNT_NOT_FOUND"
    assert result.worker_online is False
    assert result.mt5_connected is False


def test_account_without_worker(reconciliation, database):
    database.get_account.return_value = {
        "id": "account-1",
        "worker_id": None,
    }

    result = asyncio.run(
        reconciliation.reconcile_account("account-1")
    )

    assert result.action_taken == "NO_WORKER_ASSIGNED"
    assert result.worker_online is False
    assert result.mt5_connected is False


def test_worker_offline(reconciliation, worker_registry):
    worker_registry.get_worker.return_value = {
        "id": "worker-1",
        "status": "OFFLINE",
    }

    result = asyncio.run(
        reconciliation.reconcile_account("account-1")
    )

    assert result.worker_online is False
    assert result.mt5_connected is False
    assert result.action_taken == "WORKER_OFFLINE"


def test_mt5_disconnected(reconciliation, monkeypatch):
    monkeypatch.setattr(
        reconciliation,
        "_check_worker_mt5_connection",
        AsyncMock(return_value=False),
    )

    result = asyncio.run(
        reconciliation.reconcile_account("account-1")
    )

    assert result.worker_online is True
    assert result.mt5_connected is False
    assert result.action_taken == "MT5_DISCONNECTED"


def test_pending_commands_are_detected(reconciliation, database, monkeypatch):
    database.get_pending_commands.return_value = [
        {
            "id": "command-1",
            "command_type": "BUY",
            "account_id": "account-1",
            "symbol": "XAUUSDm",
            "volume": 0.04,
            "stop_loss": 3297.00,
            "take_profit": 3303.00,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ]

    monkeypatch.setattr(
        reconciliation,
        "_check_worker_mt5_connection",
        AsyncMock(return_value=True),
    )

    result = asyncio.run(
        reconciliation.reconcile_account("account-1")
    )

    assert result.pending_commands == 1
    assert result.action_taken == "PENDING_COMMANDS_WAITING"


def test_missing_fill_is_detected(reconciliation, database, monkeypatch):
    old_time = datetime.now(timezone.utc) - timedelta(seconds=60)

    database.get_pending_commands.return_value = [
        {
            "id": "command-1",
            "command_type": "BUY",
            "account_id": "account-1",
            "symbol": "XAUUSDm",
            "volume": 0.04,
            "stop_loss": 3297.00,
            "take_profit": 3303.00,
            "created_at": old_time.isoformat(),
        }
    ]

    monkeypatch.setattr(
        reconciliation,
        "_check_worker_mt5_connection",
        AsyncMock(return_value=True),
    )

    result = asyncio.run(
        reconciliation.reconcile_account("account-1")
    )

    assert result.missing_fill_detected is True
    assert result.action_taken == "MISSING_FILL_DETECTED"


def test_duplicate_order_risk_is_detected(
    reconciliation,
    database,
    monkeypatch,
):
    command_time = datetime.now(timezone.utc)

    database.get_pending_commands.return_value = [
        {
            "id": "command-1",
            "command_type": "BUY",
            "account_id": "account-1",
            "symbol": "XAUUSDm",
            "volume": 0.04,
            "stop_loss": 3297.00,
            "take_profit": 3303.00,
            "created_at": command_time.isoformat(),
        },
        {
            "id": "command-2",
            "command_type": "BUY",
            "account_id": "account-1",
            "symbol": "XAUUSDm",
            "volume": 0.04,
            "stop_loss": 3297.00,
            "take_profit": 3303.00,
            "created_at": command_time.isoformat(),
        },
    ]

    monkeypatch.setattr(
        reconciliation,
        "_check_worker_mt5_connection",
        AsyncMock(return_value=True),
    )

    result = asyncio.run(
        reconciliation.reconcile_account("account-1")
    )

    assert result.duplicate_risk_detected is True
    assert result.action_taken == "DUPLICATE_RISK_DETECTED"


def test_stale_position_is_detected(reconciliation, database, monkeypatch):
    old_time = datetime.now(timezone.utc) - timedelta(seconds=180)

    database.get_account.return_value = {
        "id": "account-1",
        "worker_id": "worker-1",
        "last_position_update_at": old_time.isoformat(),
    }

    monkeypatch.setattr(
        reconciliation,
        "_check_worker_mt5_connection",
        AsyncMock(return_value=True),
    )

    result = asyncio.run(
        reconciliation.reconcile_account("account-1")
    )

    assert result.stale_position_detected is True
    assert result.action_taken == "STALE_POSITION_DETECTED"


def test_healthy_account_has_no_action(reconciliation, monkeypatch):
    monkeypatch.setattr(
        reconciliation,
        "_check_worker_mt5_connection",
        AsyncMock(return_value=True),
    )

    result = asyncio.run(
        reconciliation.reconcile_account("account-1")
    )

    assert result.worker_online is True
    assert result.mt5_connected is True
    assert result.pending_commands == 0
    assert result.duplicate_risk_detected is False
    assert result.missing_fill_detected is False
    assert result.stale_position_detected is False
    assert result.action_taken == "NO_ACTION"
