import os
from unittest.mock import MagicMock, patch

import pytest

os_environ = {
    "SECRET_KEY": "test-secret-key",
    "DATABASE_URL": "sqlite:///:memory:",
    "ENABLE_LIVE_TRADING": "true",
    "LIVE_TRADING_AUTHORIZED": "true",
}

with patch.dict("os.environ", os_environ):
    from app import app
    from bot_manager import BotManager
    from license_auth import LicenseAuth
    from live_trading_gate import LiveTradingGate
    from order_router import OrderRouter
    from reconciliation import ReconciliationService
    from worker_registry import WorkerRegistry


@pytest.fixture
def client():
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_worker_registry():
    return MagicMock()


@pytest.fixture
def worker_registry(mock_db):
    return WorkerRegistry(db=mock_db)


@pytest.fixture
def order_router(mock_db, mock_worker_registry):
    return OrderRouter(
        db=mock_db,
        worker_registry=mock_worker_registry,
    )


@pytest.fixture
def bot_manager(mock_db, mock_order_router):
    return BotManager(
        db=mock_db,
        order_router=mock_order_router,
    )


@pytest.fixture
def license_auth(mock_db):
    return LicenseAuth(db=mock_db)


@pytest.fixture
def live_trading_gate():
    return LiveTradingGate(
        enable_live_trading=True,
        live_trading_authorized=True,
    )


@pytest.fixture
def reconciliation_service(mock_db, mock_worker_registry):
    return ReconciliationService(
        db=mock_db,
        worker_registry=mock_worker_registry,
    )


def make_worker(
    worker_id: str = "worker-1",
    account_id: str = "account-1",
    active_connections: int = 0,
    max_connections: int = 1,
) -> MagicMock:
    worker = MagicMock()

    worker.id = worker_id
    worker.account_id = account_id
    worker.worker_url = f"https://{worker_id}.example.com"
    worker.status = "online"
    worker.active_connections = active_connections
    worker.max_connections = max_connections

    return worker


def make_command() -> dict:
    return {
        "command_type": "BUY",
        "account_id": "account-1",
        "symbol": "XAUUSDm",
        "volume": 0.01,
        "stop_loss": 3297.00,
        "take_profit": 3303.00,
        "comment": "BALANCED-SCALP-1 [BOSSMODE99]",
    }


def test_health_endpoint_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "healthy"


def test_license_auth_accepts_valid_license(license_auth, mock_db):
    license_record = MagicMock()

    license_record.license_key = "BOSSMODE99"
    license_record.account_id = "account-1"
    license_record.status = "active"

    mock_db.get_license_by_key.return_value = license_record

    result = license_auth.validate_license(
        license_key="BOSSMODE99",
        account_id="account-1",
    )

    assert result["success"] is True
    assert result["license_key"] == "BOSSMODE99"


def test_license_auth_rejects_wrong_account(license_auth, mock_db):
    license_record = MagicMock()

    license_record.license_key = "BOSSMODE99"
    license_record.account_id = "account-2"
    license_record.status = "active"

    mock_db.get_license_by_key.return_value = license_record

    result = license_auth.validate_license(
        license_key="BOSSMODE99",
        account_id="account-1",
    )

    assert result["success"] is False
    assert "License is bound to another account" in result["message"]


def test_worker_registry_assigns_available_worker(
    worker_registry,
    mock_db,
):
    worker = make_worker()

    mock_db.get_online_workers.return_value = [worker]
    mock_db.increment_worker_connections.return_value = True

    result = worker_registry.assign_worker(
        account_id="account-2",
    )

    assert result["success"] is True
    assert result["worker_id"] == "worker-1"
    assert result["worker_url"] == worker.worker_url


def test_worker_registry_blocks_full_worker(
    worker_registry,
    mock_db,
):
    worker = make_worker(
        active_connections=1,
        max_connections=1,
    )

    mock_db.get_online_workers.return_value = [worker]

    result = worker_registry.assign_worker(
        account_id="account-2",
    )

    assert result["success"] is False
    assert "No worker capacity available" in result["message"]


def test_live_trading_gate_allows_authorized_command(live_trading_gate):
    result = live_trading_gate.validate(
        command=make_command(),
    )

    assert result["success"] is True
    assert result["message"] == "Live trading is authorized."


def test_live_trading_gate_blocks_unauthorized_command():
    gate = LiveTradingGate(
        enable_live_trading=True,
        live_trading_authorized=False,
    )

    result = gate.validate(
        command=make_command(),
    )

    assert result["success"] is False
    assert "Live trading is not authorized" in result["message"]


def test_order_router_routes_command(
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
        make_command()
    )

    assert result["success"] is True
    assert result["worker_id"] == "worker-1"
    assert result["command_type"] == "BUY"
    assert result["worker_url"] == worker.worker_url


def test_order_router_rejects_duplicate_command(
    order_router,
    mock_db,
):
    mock_db.get_recent_command_by_signature.return_value = MagicMock()

    result = order_router.route_command(
        make_command()
    )

    assert result["success"] is False
    assert "Duplicate order rejected" in result["message"]


def test_bot_manager_rejects_high_spread(bot_manager):
    bot_config = {
        "max_allowed_spread_pips": 35.0,
    }

    tick = {
        "bid": 3300.00,
        "ask": 3310.00,
    }

    result = bot_manager.validate_spread(
        bot_config=bot_config,
        tick=tick,
    )

    assert result["success"] is False
    assert "Spread too high" in result["message"]


def test_bot_manager_allows_acceptable_spread(bot_manager):
    bot_config = {
        "max_allowed_spread_pips": 35.0,
    }

    tick = {
        "bid": 3300.00,
        "ask": 3300.10,
    }

    result = bot_manager.validate_spread(
        bot_config=bot_config,
        tick=tick,
    )

    assert result["success"] is True


def test_reconciliation_detects_orphaned_position(
    reconciliation_service,
    mock_db,
):
    worker = make_worker()

    mock_db.get_worker_by_account.return_value = worker

    mock_db.get_open_orders_for_account.return_value = []

    reconciliation_service.worker_client.get_open_positions = MagicMock(
        return_value=[
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
    )

    result = reconciliation_service.reconcile_account(
        account_id="account-1",
    )

    assert result["success"] is True
    assert len(result["orphaned_orders"]) == 1
    assert result["orphaned_orders"][0]["ticket"] == 123456


def test_reconciliation_detects_missing_position(
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


def test_full_system_flow(
    client,
    mock_db,
    mock_worker_registry,
    worker_registry,
    order_router,
    license_auth,
    live_trading_gate,
    bot_manager,
    reconciliation_service,
):
    license_record = MagicMock()

    license_record.license_key = "BOSSMODE99"
    license_record.account_id = "account-1"
    license_record.status = "active"

    mock_db.get_license_by_key.return_value = license_record

    license_result = license_auth.validate_license(
        license_key="BOSSMODE99",
        account_id="account-1",
    )

    assert license_result["success"] is True

    worker = make_worker()

    mock_db.get_online_workers.return_value = [worker]
    mock_db.increment_worker_connections.return_value = True

    worker_result = worker_registry.assign_worker(
        account_id="account-2",
    )

    assert worker_result["success"] is True

    mock_db.get_recent_command_by_signature.return_value = None
    mock_db.create_command.return_value = MagicMock()

    mock_worker_registry.assign_worker.return_value = {
        "success": True,
        "worker_id": "worker-1",
        "worker_url": worker.worker_url,
    }

    routing_result = order_router.route_command(
        make_command()
    )

    assert routing_result["success"] is True
    assert routing_result["worker_id"] == "worker-1"

    gate_result = live_trading_gate.validate(
        command=make_command(),
    )

    assert gate_result["success"] is True

    bot_config = {
        "max_allowed_spread_pips": 35.0,
    }

    tick = {
        "bid": 3300.00,
        "ask": 3300.10,
    }

    spread_result = bot_manager.validate_spread(
        bot_config=bot_config,
        tick=tick,
    )

    assert spread_result["success"] is True

    mock_db.get_worker_by_account.return_value = worker

    mock_db.get_open_orders_for_account.return_value = []

    reconciliation_service.worker_client.get_open_positions = MagicMock(
        return_value=[]
    )

    reconciliation_result = reconciliation_service.reconcile_account(
        account_id="account-1",
    )

    assert reconciliation_result["success"] is True
    assert reconciliation_result["orphaned_orders"] == []
    assert reconciliation_result["missing_orders"] == []
