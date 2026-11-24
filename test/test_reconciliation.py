from unittest.mock import MagicMock

import pytest

from reconciliation import ReconciliationService


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_worker_registry():
    return MagicMock()


@pytest.fixture
def reconciliation_service(mock_db, mock_worker_registry):
    return ReconciliationService(
        db=mock_db,
        worker_registry=mock_worker_registry,
    )


def make_worker(
    worker_id: str = "worker-1",
    account_id: str = "account-1",
    worker_url: str = "https://worker-1.example.com",
) -> MagicMock:
    worker = MagicMock()

    worker.id = worker_id
    worker.account_id = account_id
    worker.worker_url = worker_url

    return worker


def make_open_position(
    ticket: int = 123456,
    symbol: str = "XAUUSDm",
    direction: str = "BUY",
    volume: float = 0.01,
    comment: str = "BALANCED-SCALP-1 [BOSSMODE99]",
) -> dict:
    return {
        "ticket": ticket,
        "symbol": symbol,
        "type": direction,
        "volume": volume,
        "price_open": 3300.00,
        "profit": 0.00,
        "comment": comment,
    }


def test_reconcile_no_open_positions(reconciliation_service, mock_db):
    worker = make_worker()

    mock_db.get_worker_by_account.return_value = worker

    mock_db.get_open_orders_for_account.return_value = []

    reconciliation_service.worker_client.get_open_positions = MagicMock(
        return_value=[]
    )

    result = reconciliation_service.reconcile_account(
        account_id="account-1",
    )

    assert result["success"] is True
    assert result["open_positions"] == []
    assert result["orphaned_orders"] == []
    assert result["missing_orders"] == []


def test_reconcile_detects_orphaned_position(
    reconciliation_service,
    mock_db,
):
    worker = make_worker()

    mock_db.get_worker_by_account.return_value = worker

    mock_db.get_open_orders_for_account.return_value = []

    reconciliation_service.worker_client.get_open_positions = MagicMock(
        return_value=[
            make_open_position(
                ticket=123456,
            )
        ]
    )

    result = reconciliation_service.reconcile_account(
        account_id="account-1",
    )

    assert result["success"] is True
    assert len(result["orphaned_orders"]) == 1
    assert result["orphaned_orders"][0]["ticket"] == 123456


def test_reconcile_detects_missing_position(
    reconciliation_service,
    mock_db,
):
    worker = make_worker()

    mock_db.get_worker_by_account.return_value = worker

    mock_db.get_open_orders_for_account.return_value = [
        {
            "ticket": 123456,
            "symbol": "XAUUSDm",
            "direction": "BUY",
            "volume": 0.01,
            "comment": "BALANCED-SCALP-1 [BOSSMODE99]",
        }
    ]

    reconciliation_service.worker_client.get_open_positions = MagicMock(
        return_value=[]
    )

    result = reconciliation_service.reconcile_account(
        account_id="account-1",
    )

    assert result["success"] is True
    assert len(result["missing_orders"]) == 1
    assert result["missing_orders"][0]["ticket"] == 123456


def test_reconcile_matches_open_position(
    reconciliation_service,
    mock_db,
):
    worker = make_worker()

    mock_db.get_worker_by_account.return_value = worker

    mock_db.get_open_orders_for_account.return_value = [
        {
            "ticket": 123456,
            "symbol": "XAUUSDm",
            "direction": "BUY",
            "volume": 0.01,
            "comment": "BALANCED-SCALP-1 [BOSSMODE99]",
        }
    ]

    reconciliation_service.worker_client.get_open_positions = MagicMock(
        return_value=[
            make_open_position(
                ticket=123456,
            )
        ]
    )

    result = reconciliation_service.reconcile_account(
        account_id="account-1",
    )

    assert result["success"] is True
    assert result["open_positions"] == [
        {
            "ticket": 123456,
            "symbol": "XAUUSDm",
            "type": "BUY",
            "volume": 0.01,
            "price_open": 3300.00,
            "profit": 0.00,
            "comment": "BALANCED-SCALP-1 [BOSSMODE99]",
        }
    ]
    assert result["orphaned_orders"] == []
    assert result["missing_orders"] == []


def test_close_orphaned_positions(
    reconciliation_service,
    mock_db,
):
    worker = make_worker()

    mock_db.get_worker_by_account.return_value = worker

    reconciliation_service.worker_client.close_position = MagicMock(
        return_value={
            "success": True,
            "message": "Position 123456 closed with SELL order.",
        }
    )

    result = reconciliation_service.close_orphaned_position(
        account_id="account-1",
        ticket=123456,
    )

    assert result["success"] is True
    assert result["message"] == "Position 123456 closed with SELL order."

    reconciliation_service.worker_client.close_position.assert_called_once_with(
        123456
    )


def test_close_orphaned_position_failure(
    reconciliation_service,
    mock_db,
):
    worker = make_worker()

    mock_db.get_worker_by_account.return_value = worker

    reconciliation_service.worker_client.close_position = MagicMock(
        return_value={
            "success": False,
            "message": "MT5 close rejected.",
        }
    )

    result = reconciliation_service.close_orphaned_position(
        account_id="account-1",
        ticket=123456,
    )

    assert result["success"] is False
    assert result["message"] == "MT5 close rejected."
