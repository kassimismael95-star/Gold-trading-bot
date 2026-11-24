from unittest.mock import MagicMock, patch

import pytest

os_environ = {
    "SECRET_KEY": "test-secret-key",
    "DATABASE_URL": "sqlite:///:memory:",
    "ENABLE_LIVE_TRADING": "true",
}

with patch.dict("os.environ", os_environ):
    from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client


def auth_headers(token: str = "test-token") -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def test_health_endpoint_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "healthy"


def test_register_user_requires_email(client):
    response = client.post(
        "/api/auth/register",
        json={
            "password": "password123",
        },
    )

    assert response.status_code == 400

    data = response.get_json()

    assert data["status"] == "error"
    assert "Email is required" in data["message"]


def test_register_user_requires_password(client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
        },
    )

    assert response.status_code == 400

    data = response.get_json()

    assert data["status"] == "error"
    assert "Password is required" in data["message"]


def test_login_requires_email(client):
    response = client.post(
        "/api/auth/login",
        json={
            "password": "password123",
        },
    )

    assert response.status_code == 400

    data = response.get_json()

    assert data["status"] == "error"
    assert "Email is required" in data["message"]


def test_login_requires_password(client):
    response = client.post(
        "/api/auth/login",
        json={
            "email": "user@example.com",
        },
    )

    assert response.status_code == 400

    data = response.get_json()

    assert data["status"] == "error"
    assert "Password is required" in data["message"]


def test_accounts_require_authentication(client):
    response = client.get("/api/accounts")

    assert response.status_code == 401

    data = response.get_json()

    assert data["status"] == "error"
    assert "Authentication required" in data["message"]


def test_workers_require_authentication(client):
    response = client.get("/api/workers")

    assert response.status_code == 401

    data = response.get_json()

    assert data["status"] == "error"
    assert "Authentication required" in data["message"]


def test_commands_require_authentication(client):
    response = client.post(
        "/api/commands",
        json={
            "command_type": "BUY",
        },
    )

    assert response.status_code == 401

    data = response.get_json()

    assert data["status"] == "error"
    assert "Authentication required" in data["message"]


def test_command_rejects_unsupported_type(client):
    with patch(
        "app.auth_required",
        return_value=lambda f: f,
    ):
        response = client.post(
            "/api/commands",
            headers=auth_headers(),
            json={
                "command_type": "INVALID",
                "account_id": 1,
            },
        )

    assert response.status_code == 400

    data = response.get_json()

    assert data["status"] == "error"
    assert "Unsupported command type" in data["message"]


def test_command_rejects_zero_volume(client):
    with patch(
        "app.auth_required",
        return_value=lambda f: f,
    ):
        response = client.post(
            "/api/commands",
            headers=auth_headers(),
            json={
                "command_type": "BUY",
                "account_id": 1,
                "volume": 0,
                "stop_loss": 3297.00,
                "take_profit": 3303.00,
            },
        )

    assert response.status_code == 400

    data = response.get_json()

    assert data["status"] == "error"
    assert "Volume must be greater than zero" in data["message"]


def test_command_rejects_missing_stop_loss(client):
    with patch(
        "app.auth_required",
        return_value=lambda f: f,
    ):
        response = client.post(
            "/api/commands",
            headers=auth_headers(),
            json={
                "command_type": "BUY",
                "account_id": 1,
                "volume": 0.01,
                "stop_loss": 0,
                "take_profit": 3303.00,
            },
        )

    assert response.status_code == 400

    data = response.get_json()

    assert data["status"] == "error"
    assert "Stop loss and take profit are required" in data["message"]


def test_command_rejects_missing_take_profit(client):
    with patch(
        "app.auth_required",
        return_value=lambda f: f,
    ):
        response = client.post(
            "/api/commands",
            headers=auth_headers(),
            json={
                "command_type": "BUY",
                "account_id": 1,
                "volume": 0.01,
                "stop_loss": 3297.00,
                "take_profit": 0,
            },
        )

    assert response.status_code == 400

    data = response.get_json()

    assert data["status"] == "error"
    assert "Stop loss and take profit are required" in data["message"]


def test_close_basket_does_not_require_sl_tp(client):
    with patch(
        "app.auth_required",
        return_value=lambda f: f,
    ):
        with patch(
            "app.order_router.route_command",
            return_value={
                "success": True,
                "message": "CLOSE_BASKET command routed.",
                "worker_id": "worker-1",
                "command_type": "CLOSE_BASKET",
            },
        ):
            response = client.post(
                "/api/commands",
                headers=auth_headers(),
                json={
                    "command_type": "CLOSE_BASKET",
                    "account_id": 1,
                    "symbol": "XAUUSDm",
                },
            )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "success"
    assert data["command_type"] == "CLOSE_BASKET"


def test_live_trading_flag_is_enabled():
    from app import ENABLE_LIVE_TRADING

    assert ENABLE_LIVE_TRADING is True
