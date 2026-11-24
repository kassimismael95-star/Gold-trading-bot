import os
from unittest.mock import MagicMock, patch

import pytest

os_environ = {
    "SECRET_KEY": "test-secret-key",
    "DATABASE_URL": "sqlite:///:memory:",
    "ENABLE_LIVE_TRADING": "true",
}

with patch.dict("os.environ", os_environ):
    from app import app
    from security import hash_password, verify_password


@pytest.fixture
def client():
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client


def test_hash_password_is_not_plain_text():
    password = "password123"

    hashed = hash_password(password)

    assert hashed != password
    assert len(hashed) > 0


def test_verify_password_success():
    password = "password123"

    hashed = hash_password(password)

    assert verify_password(password, hashed) is True


def test_verify_password_failure():
    password = "password123"

    hashed = hash_password(password)

    assert verify_password("wrong-password", hashed) is False


def test_password_hash_is_deterministic_for_same_password():
    password = "password123"

    hash_1 = hash_password(password)
    hash_2 = hash_password(password)

    assert hash_1 == hash_2


def test_password_hash_differs_for_different_passwords():
    hash_1 = hash_password("password123")
    hash_2 = hash_password("password456")

    assert hash_1 != hash_2


def test_health_endpoint_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200


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


def test_invalid_token_is_rejected(client):
    response = client.get(
        "/api/accounts",
        headers={
            "Authorization": "Bearer invalid-token",
        },
    )

    assert response.status_code == 401

    data = response.get_json()

    assert data["status"] == "error"
    assert "Invalid or expired token" in data["message"]


def test_missing_token_is_rejected(client):
    response = client.get("/api/accounts")

    assert response.status_code == 401

    data = response.get_json()

    assert data["status"] == "error"
    assert "Authentication required" in data["message"]


def test_sql_injection_is_rejected(client):
    response = client.post(
        "/api/auth/login",
        json={
            "email": "' OR 1=1 --",
            "password": "password123",
        },
    )

    assert response.status_code in [400, 401]

    data = response.get_json()

    assert data["status"] == "error"


def test_xss_payload_is_not_executed(client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "<script>alert(1)</script>",
            "password": "password123",
        },
    )

    assert response.status_code in [200, 400]

    data = response.get_json()

    assert "<script>" not in str(data)


def test_worker_secret_is_required(client):
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
