import os
from unittest.mock import MagicMock, patch

import pytest

os_environ = {
    "SECRET_KEY": "test-secret-key",
    "DATABASE_URL": "sqlite:///:memory:",
    "ENABLE_LIVE_TRADING": "true",
    "LIVE_TRADING_AUTHORIZED": "false",
    "WORKER_SHARED_SECRET": "test-worker-secret",
    "WORKER_ID": "worker-1",
    "WORKER_PORT": "8080",
}

with patch.dict("os.environ", os_environ):
    from app import app
    from bot_manager import BotManager
    from command_executor import CommandExecutor
    from license_auth import LicenseAuth
    from live_trading_gate import LiveTradingGate
    from mt5_client import MT5Client
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
        live_trading_authorized=False,
    )


@pytest.fixture
def mt5_client():
    return MT5Client()


@pytest.fixture
def command_executor(mt5_client):
    return CommandExecutor(mt5_client=mt5_client)


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


def test_final_validation_control_plane_health(client):
    response = client.get("/health")

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "healthy"


def test_final_validation_license_auth(license_auth, mock_db):
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


def test_final_validation_worker_capacity(worker_registry, mock_db):
    worker = make_worker()

    mock_db.get_online_workers.return_value = [worker]
    mock_db.increment_worker_connections.return_value = True

    result = worker_registry.assign_worker(
        account_id="account-2",
    )

    assert result["success"] is True
    assert result["worker_id"] == "worker-1"


def test_final_validation_live_trading_gate(live_trading_gate):
    result = live_trading_gate.validate(
        command=make_command(),
    )

    assert result["success"] is False
    assert "Live trading is not authorized" in result["message"]


def test_final_validation_order_router(
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


def test_final_validation_bot_manager(bot_manager):
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


def test_final_validation_mt5_client(mt5_client):
    with patch(
        "worker.mt5_client.mt5.initialize",
        return_value=True,
    ):
        result = mt5_client.initialize()

    assert result.connected is True
    assert mt5_client.initialized is True


def test_final_validation_command_executor(command_executor):
    command = make_command()

    command_executor.mt5_client.open_market_order = MagicMock(
        return_value={
            "success": True,
            "message": "BUY order opened on XAUUSDm with 0.01 lots.",
            "order_ticket": 123456,
            "deal_ticket": 789012,
            "price": 3300.10,
        }
    )

    result = command_executor.execute(command)

    assert result.success is True
    assert result.command_type == "BUY"
    assert result.response["order_ticket"] == 123456


def test_final_validation_reconciliation(
    reconciliation_service,
    mock_db,
):
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
    assert result["orphaned_orders"] == []
    assert result["missing_orders"] == []


def test_final_validation_worker_security(client):
    response = client.post(
        "/workers/worker-1/commands",
        json={
            "command_type": "BUY",
            "account_id": "account-1",
            "worker_id": "worker-1",
        },
    )

    assert response.status_code == 401

    data = response.get_json()

    assert data["status"] == "error"
    assert "Unauthorized worker request" in data["message"]


def test_final_validation_environment():
    assert os.environ.get("SECRET_KEY") == "test-secret-key"
    assert os.environ.get("DATABASE_URL") == "sqlite:///:memory:"
    assert os.environ.get("ENABLE_LIVE_TRADING") == "true"
    assert os.environ.get("LIVE_TRADING_AUTHORIZED") == "false"
    assert os.environ.get("WORKER_SHARED_SECRET") == "test-worker-secret"
    assert os.environ.get("WORKER_ID") == "worker-1"
    assert os.environ.get("WORKER_PORT") == "8080"


def test_final_validation_full_flow(
    license_auth,
    mock_db,
    worker_registry,
    live_trading_gate,
    order_router,
    mock_worker_registry,
    bot_manager,
    mt5_client,
    command_executor,
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

    gate_result = live_trading_gate.validate(
        command=make_command(),
    )

    assert gate_result["success"] is False

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

    with patch(
        "worker.mt5_client.mt5.initialize",
        return_value=True,
    ):
        mt5_result = mt5_client.initialize()

    assert mt5_result.connected is True

    command_executor.mt5_client.open_market_order = MagicMock(
        return_value={
            "success": True,
            "message": "BUY order opened on XAUUSDm with 0.01 lots.",
            "order_ticket": 123456,
            "deal_ticket": 789012,
            "price": 3300.10,
        }
    )

    execution_result = command_executor.execute(
        make_command()
    )

    assert execution_result.success is True

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
