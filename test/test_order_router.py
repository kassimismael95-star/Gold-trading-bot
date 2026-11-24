from unittest.mock import MagicMock

import pytest

from order_router import OrderRouter


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_worker_registry():
    return MagicMock()


@pytest.fixture
def order_router(mock_db, mock_worker_registry):
    return OrderRouter(
        db=mock_db,
        worker_registry=mock_worker_registry,
    )


def make_command(
    command_type: str = "BUY",
    account_id: str = "account-1",
    symbol: str = "XAUUSDm",
    volume: float = 0.01,
    stop_loss: float = 3297.00,
    take_profit: float = 3303.00,
    comment: str = "BALANCED-SCALP-1 [BOSSMODE99]",
) -> dict:
    return {
        "command_type": command_type,
        "account_id": account_id,
        "symbol": symbol,
        "volume": volume,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "comment": comment,
    }


def make_worker(
    worker_id: str = "worker-1",
    worker_url: str = "https://worker-1.example.com",
) -> MagicMock:
    worker = MagicMock()

    worker.id = worker_id
    worker.worker_url = worker_url

    return worker


def test_rejects_unsupported_command(order_router):
    result = order_router.route_command(
        make_command("INVALID")
    )

    assert result["success"] is False
    assert "Unsupported command type" in result["message"]


def test_requires_account_id(order_router):
    command = make_command()

    command["account_id"] = ""

    result = order_router.route_command(command)

    assert result["success"] is False
    assert "Account ID is required" in result["message"]


def test_rejects_zero_volume(order_router):
    command = make_command()

    command["volume"] = 0

    result = order_router.route_command(command)

    assert result["success"] is False
    assert "Volume must be greater than zero" in result["message"]


def test_rejects_missing_stop_loss(order_router):
    command = make_command()

    command["stop_loss"] = 0

    result = order_router.route_command(command)

    assert result["success"] is False
    assert "Stop loss and take profit are required" in result["message"]


def test_rejects_missing_take_profit(order_router):
    command = make_command()

    command["take_profit"] = 0

    result = order_router.route_command(command)

    assert result["success"] is False
    assert "Stop loss and take profit are required" in result["message"]


def test_rejects_duplicate_order(order_router, mock_db):
    mock_db.get_recent_command_by_signature.return_value = MagicMock()

    result = order_router.route_command(
        make_command()
    )

    assert result["success"] is False
    assert "Duplicate order rejected" in result["message"]


def test_rejects_when_no_worker_available(
    order_router,
    mock_worker_registry,
):
    mock_db.get_recent_command_by_signature.return_value = None

    mock_worker_registry.assign_worker.return_value = {
        "success": False,
        "message": "No worker capacity available",
    }

    result = order_router.route_command(
        make_command()
    )

    assert result["success"] is False
    assert "No worker capacity available" in result["message"]


def test_routes_buy_command(
    order_router,
    mock_db,
    mock_worker_registry,
):
    mock_db.get_recent_command_by_signature.return_value = None
    mock_db.create_command.return_value = MagicMock()

    worker = make_worker()

    mock_worker_registry.assign_worker.return_value = {
        "success": True,
        "worker_id": "worker-1",
        "worker_url": worker.worker_url,
    }

    result = order_router.route_command(
        make_command("BUY")
    )

    assert result["success"] is True
    assert result["worker_id"] == "worker-1"
    assert result["command_type"] == "BUY"
    assert result["worker_url"] == worker.worker_url


def test_routes_sell_command(
    order_router,
    mock_db,
    mock_worker_registry,
):
    mock_db.get_recent_command_by_signature.return_value = None
    mock_db.create_command.return_value = MagicMock()

    worker = make_worker(
        worker_id="worker-2",
        worker_url="https://worker-2.example.com",
    )

    mock_worker_registry.assign_worker.return_value = {
        "success": True,
        "worker_id": "worker-2",
        "worker_url": worker.worker_url,
    }

    result = order_router.route_command(
        make_command("SELL")
    )

    assert result["success"] is True
    assert result["worker_id"] == "worker-2"
    assert result["command_type"] == "SELL"
    assert result["worker_url"] == worker.worker_url


def test_routes_close_basket_command(
    order_router,
    mock_db,
    mock_worker_registry,
):
    mock_db.get_recent_command_by_signature.return_value = None
    mock_db.create_command.return_value = MagicMock()

    worker = make_worker()

    mock_worker_registry.assign_worker.return_value = {
        "success": True,
        "worker_id": "worker-1",
        "worker_url": worker.worker_url,
    }

    result = order_router.route_command(
        make_command("CLOSE_BASKET")
    )

    assert result["success"] is True
    assert result["worker_id"] == "worker-1"
    assert result["command_type"] == "CLOSE_BASKET"
    assert result["worker_url"] == worker.worker_url


def test_close_basket_does_not_require_sl_tp(
    order_router,
    mock_db,
    mock_worker_registry,
):
    command = make_command("CLOSE_BASKET")

    command["stop_loss"] = 0
    command["take_profit"] = 0

    mock_db.get_recent_command_by_signature.return_value = None
    mock_db.create_command.return_value = MagicMock()

    worker = make_worker()

    mock_worker_registry.assign_worker.return_value = {
        "success": True,
        "worker_id": "worker-1",
        "worker_url": worker.worker_url,
    }

    result = order_router.route_command(command)

    assert result["success"] is True
    assert result["command_type"] == "CLOSE_BASKET"
