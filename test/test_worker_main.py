import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("WORKER_ID", "worker-1")
os.environ.setdefault("WORKER_SHARED_SECRET", "test-worker-secret")

from worker.main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client


def auth_headers():
    return {
        "X-Worker-Secret": "test-worker-secret",
        "Content-Type": "application/json",
    }


def test_health_root_is_public(client):
    response = client.get("/")

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "online"
    assert data["worker_id"] == "worker-1"


def test_health_ping_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "healthy"
    assert data["worker_id"] == "worker-1"


def test_worker_status_requires_secret(client):
    response = client.get("/workers/worker-1/status")

    assert response.status_code == 401

    data = response.get_json()

    assert data["status"] == "error"
    assert "Unauthorized" in data["message"]


def test_worker_status_rejects_wrong_worker(client):
    response = client.get(
        "/workers/worker-2/status",
        headers=auth_headers(),
    )

    assert response.status_code == 403

    data = response.get_json()

    assert data["status"] == "error"
    assert "does not match" in data["message"]


def test_worker_status_returns_online(client):
    response = client.get(
        "/workers/worker-1/status",
        headers=auth_headers(),
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "online"
    assert data["worker_id"] == "worker-1"


def test_connect_requires_credentials(client):
    response = client.post(
        "/workers/worker-1/connect",
        headers=auth_headers(),
        json={},
    )

    assert response.status_code == 400

    data = response.get_json()

    assert data["status"] == "error"
    assert "MT5 login, password, and server are required" in data["message"]


def test_connect_rejects_wrong_worker(client):
    response = client.post(
        "/workers/worker-2/connect",
        headers=auth_headers(),
        json={
            "mt5_login": "123456",
            "mt5_password": "password",
            "mt5_server": "Exness-MT5Real",
        },
    )

    assert response.status_code == 403

    data = response.get_json()

    assert data["status"] == "error"
    assert "does not match" in data["message"]


def test_command_requires_authorization(client):
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
    assert "Unauthorized" in data["message"]


def test_command_rejects_wrong_worker(client):
    response = client.post(
        "/workers/worker-2/commands",
        headers=auth_headers(),
        json={
            "command_type": "BUY",
            "account_id": "account-1",
            "worker_id": "worker-2",
        },
    )

    assert response.status_code == 403

    data = response.get_json()

    assert data["status"] == "error"
    assert "does not match" in data["message"]


def test_command_rejects_unconnected_mt5(client):
    from worker.main import mt5_client

    mt5_client.connected = False

    response = client.post(
        "/workers/worker-1/commands",
        headers=auth_headers(),
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


def test_command_executes_buy(client):
    from worker.main import command_executor, mt5_client

    mt5_client.connected = True

    mock_execute = MagicMock(
        return_value=MagicMock(
            success=True,
            message="BUY order opened on XAUUSDm with 0.01 lots.",
            command_type="BUY",
            account_id="account-1",
            worker_id="worker-1",
            response={
                "order_ticket": 123456,
                "deal_ticket": 789012,
            },
        )
    )

    command_executor.execute = mock_execute

    response = client.post(
        "/workers/worker-1/commands",
        headers=auth_headers(),
        json={
            "command_type": "BUY",
            "account_id": "account-1",
            "worker_id": "worker-1",
            "symbol": "XAUUSDm",
            "volume": 0.01,
            "stop_loss": 3297.00,
            "take_profit": 3303.00,
            "comment": "BALANCED-SCALP-1 [BOSSMODE99]",
        },
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "success"
    assert data["success"] is True
    assert data["command_type"] == "BUY"
    assert data["response"]["order_ticket"] == 123456

    mock_execute.assert_called_once()


def test_command_executes_close_basket(client):
    from worker.main import command_executor, mt5_client

    mt5_client.connected = True

    mock_execute = MagicMock(
        return_value=MagicMock(
            success=True,
            message="Closed 3/3 positions.",
            command_type="CLOSE_BASKET",
            account_id="account-1",
            worker_id="worker-1",
            response={
                "closed_count": 3,
                "errors": [],
            },
        )
    )

    command_executor.execute = mock_execute

    response = client.post(
        "/workers/worker-1/commands",
        headers=auth_headers(),
        json={
            "command_type": "CLOSE_BASKET",
            "account_id": "account-1",
            "worker_id": "worker-1",
            "symbol": "XAUUSDm",
        },
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "success"
    assert data["command_type"] == "CLOSE_BASKET"
    assert data["response"]["closed_count"] == 3

    mock_execute.assert_called_once()
