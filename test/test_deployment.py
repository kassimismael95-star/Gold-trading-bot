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
    from worker.main import worker_app


@pytest.fixture
def client():
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client


@pytest.fixture
def worker_client():
    worker_app.config["TESTING"] = True

    with worker_app.test_client() as client:
        yield client


def test_required_environment_variables_are_set():
    assert os.environ.get("SECRET_KEY") == "test-secret-key"
    assert os.environ.get("DATABASE_URL") == "sqlite:///:memory:"
    assert os.environ.get("ENABLE_LIVE_TRADING") == "true"
    assert os.environ.get("LIVE_TRADING_AUTHORIZED") == "false"
    assert os.environ.get("WORKER_SHARED_SECRET") == "test-worker-secret"
    assert os.environ.get("WORKER_ID") == "worker-1"
    assert os.environ.get("WORKER_PORT") == "8080"


def test_live_trading_is_enabled():
    from app import ENABLE_LIVE_TRADING

    assert ENABLE_LIVE_TRADING is True


def test_live_trading_authorization_is_disabled():
    from live_trading_gate import LiveTradingGate

    gate = LiveTradingGate(
        enable_live_trading=True,
        live_trading_authorized=False,
    )

    result = gate.validate(
        command={
            "command_type": "BUY",
            "account_id": "account-1",
            "symbol": "XAUUSDm",
            "volume": 0.01,
            "stop_loss": 3297.00,
            "take_profit": 3303.00,
        }
    )

    assert result["success"] is False
    assert "Live trading is not authorized" in result["message"]


def test_control_plane_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "healthy"


def test_worker_health_endpoint(worker_client):
    response = worker_client.get("/health")

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "healthy"
    assert data["worker_id"] == "worker-1"


def test_worker_requires_shared_secret(worker_client):
    response = worker_client.get("/workers/worker-1/status")

    assert response.status_code == 401

    data = response.get_json()

    assert data["status"] == "error"
    assert "Unauthorized worker request" in data["message"]


def test_worker_accepts_correct_shared_secret(worker_client):
    response = worker_client.get(
        "/workers/worker-1/status",
        headers={
            "X-Worker-Secret": "test-worker-secret",
        },
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "online"
    assert data["worker_id"] == "worker-1"


def test_worker_rejects_wrong_worker_id(worker_client):
    response = worker_client.get(
        "/workers/worker-2/status",
        headers={
            "X-Worker-Secret": "test-worker-secret",
        },
    )

    assert response.status_code == 403

    data = response.get_json()

    assert data["status"] == "error"
    assert "does not match" in data["message"]


def test_worker_command_requires_shared_secret(worker_client):
    response = worker_client.post(
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


def test_worker_command_rejects_unconnected_mt5(worker_client):
    from worker.main import mt5_client

    mt5_client.connected = False

    response = worker_client.post(
        "/workers/worker-1/commands",
        headers={
            "X-Worker-Secret": "test-worker-secret",
            "Content-Type": "application/json",
        },
        json={
            "command_type": "BUY",
            "account_id": "account-1",
            "worker_id": "worker-1",
        },
    )

    assert response.status_code == 409

    data = response.get_json()

    assert data["status"] == "error"
    assert "MT5 account is not connected" in data["message"]


def test_database_url_is_configured():
    database_url = os.environ.get("DATABASE_URL")

    assert database_url is not None
    assert len(database_url) > 0


def test_worker_shared_secret_is_configured():
    worker_shared_secret = os.environ.get("WORKER_SHARED_SECRET")

    assert worker_shared_secret is not None
    assert len(worker_shared_secret) > 0


def test_worker_id_is_configured():
    worker_id = os.environ.get("WORKER_ID")

    assert worker_id is not None
    assert len(worker_id) > 0
