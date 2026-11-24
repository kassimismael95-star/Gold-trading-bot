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


def make_buy_command() -> dict:
    return {
        "command_type": "BUY",
        "account_id": 1,
        "symbol": "XAUUSDm",
        "volume": 0.01,
        "stop_loss": 3297.00,
        "take_profit": 3303.00,
        "comment": "BALANCED-SCALP-1 [BOSSMODE99]",
    }


def make_sell_command() -> dict:
    return {
        "command_type": "SELL",
        "account_id": 1,
        "symbol": "XAUUSDm",
        "volume": 0.01,
        "stop_loss": 3303.00,
        "take_profit": 3297.00,
        "comment": "BALANCED-SCALP-1 [BOSSMODE99]",
    }


def make_close_basket_command() -> dict:
    return {
        "command_type": "CLOSE_BASKET",
        "account_id": 1,
        "symbol": "XAUUSDm",
    }


def test_health_endpoint_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "healthy"


def test_register_user_success(client):
    with patch(
        "app.create_user",
        return_value=MagicMock(
            id=1,
            email="user@example.com",
        ),
    ):
        response = client.post(
            "/api/auth/register",
            json={
                "email": "user@example.com",
                "password": "password123",
            },
        )

    assert response.status_code == 201

    data = response.get_json()

    assert data["status"] == "success"
    assert data["message"] == "User registered successfully."


def test_login_success(client):
    with patch(
        "app.authenticate_user",
        return_value=MagicMock(
            id=1,
            email="user@example.com",
        ),
    ):
        with patch(
            "app.create_access_token",
            return_value="test-token",
        ):
            response = client.post(
                "/api/auth/login",
                json={
                    "email": "user@example.com",
                    "password": "password123",
                },
            )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "success"
    assert data["token"] == "test-token"


def test_register_account_success(client):
    with patch(
        "app.auth_required",
        return_value=lambda f: f,
    ):
        with patch(
            "app.create_account",
            return_value=MagicMock(
                id=1,
                account_name="Gold Scalper Account",
            ),
        ):
            response = client.post(
                "/api/accounts",
                headers=auth_headers(),
                json={
                    "account_name": "Gold Scalper Account",
                    "broker_name": "Exness",
                    "account_number": "123456",
                    "server_name": "Exness-MT5Real",
                    "account_type": "real",
                },
            )

    assert response.status_code == 201

    data = response.get_json()

    assert data["status"] == "success"
    assert data["message"] == "Account registered successfully."


def test_register_worker_success(client):
    with patch(
        "app.auth_required",
        return_value=lambda f: f,
    ):
        with patch(
            "app.register_worker",
            return_value={
                "success": True,
                "message": "Worker registered successfully.",
                "worker_id": "worker-1",
            },
        ):
            response = client.post(
                "/api/workers",
                headers=auth_headers(),
                json={
                    "worker_id": "worker-1",
                    "account_id": 1,
                    "worker_url": "https://worker-1.example.com",
                },
            )

    assert response.status_code == 201

    data = response.get_json()

    assert data["status"] == "success"
    assert data["message"] == "Worker registered successfully."
    assert data["worker_id"] == "worker-1"


def test_buy_command_routes_to_worker(client):
    with patch(
        "app.auth_required",
        return_value=lambda f: f,
    ):
        with patch(
            "app.order_router.route_command",
            return_value={
                "success": True,
                "message": "BUY command routed.",
                "worker_id": "worker-1",
                "worker_url": "https://worker-1.example.com",
                "command_type": "BUY",
            },
        ):
            response = client.post(
                "/api/commands",
                headers=auth_headers(),
                json=make_buy_command(),
            )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "success"
    assert data["command_type"] == "BUY"
    assert data["worker_id"] == "worker-1"
    assert data["worker_url"] == "https://worker-1.example.com"


def test_sell_command_routes_to_worker(client):
    with patch(
        "app.auth_required",
        return_value=lambda f: f,
    ):
        with patch(
            "app.order_router.route_command",
            return_value={
                "success": True,
                "message": "SELL command routed.",
                "worker_id": "worker-1",
                "worker_url": "https://worker-1.example.com",
                "command_type": "SELL",
            },
        ):
            response = client.post(
                "/api/commands",
                headers=auth_headers(),
                json=make_sell_command(),
            )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "success"
    assert data["command_type"] == "SELL"
    assert data["worker_id"] == "worker-1"
    assert data["worker_url"] == "https://worker-1.example.com"


def test_close_basket_command_routes_to_worker(client):
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
                "worker_url": "https://worker-1.example.com",
                "command_type": "CLOSE_BASKET",
            },
        ):
            response = client.post(
                "/api/commands",
                headers=auth_headers(),
                json=make_close_basket_command(),
            )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "success"
    assert data["command_type"] == "CLOSE_BASKET"
    assert data["worker_id"] == "worker-1"
    assert data["worker_url"] == "https://worker-1.example.com"


def test_end_to_end_buy_command_flow(client):
    with patch(
        "app.auth_required",
        return_value=lambda f: f,
    ):
        with patch(
            "app.order_router.route_command",
            return_value={
                "success": True,
                "message": "BUY command routed.",
                "worker_id": "worker-1",
                "worker_url": "https://worker-1.example.com",
                "command_type": "BUY",
            },
        ):
            register_response = client.post(
                "/api/auth/register",
                json={
                    "email": "user@example.com",
                    "password": "password123",
                },
            )

            assert register_response.status_code == 201

            login_response = client.post(
                "/api/auth/login",
                json={
                    "email": "user@example.com",
                    "password": "password123",
                },
            )

            assert login_response.status_code == 200

            command_response = client.post(
                "/api/commands",
                headers=auth_headers(),
                json=make_buy_command(),
            )

            assert command_response.status_code == 200

            command_data = command_response.get_json()

            assert command_data["status"] == "success"
            assert command_data["command_type"] == "BUY"
            assert command_data["worker_id"] == "worker-1"


def test_end_to_end_close_basket_flow(client):
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
                "worker_url": "https://worker-1.example.com",
                "command_type": "CLOSE_BASKET",
            },
        ):
            register_response = client.post(
                "/api/auth/register",
                json={
                    "email": "user@example.com",
                    "password": "password123",
                },
            )

            assert register_response.status_code == 201

            login_response = client.post(
                "/api/auth/login",
                json={
                    "email": "user@example.com",
                    "password": "password123",
                },
            )

            assert login_response.status_code == 200

            command_response = client.post(
                "/api/commands",
                headers=auth_headers(),
                json=make_close_basket_command(),
            )

            assert command_response.status_code == 200

            command_data = command_response.get_json()

            assert command_data["status"] == "success"
            assert command_data["command_type"] == "CLOSE_BASKET"
            assert command_data["worker_id"] == "worker-1"
