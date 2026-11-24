import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from execution.order_router import OrderRouter


@pytest.fixture
def database():
    database = MagicMock()

    database.get_account.return_value = {
        "id": "account-1",
        "worker_id": "worker-1",
    }

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
def router(database, worker_registry):
    return OrderRouter(
        database=database,
        worker_registry=worker_registry,
    )


def test_rejects_missing_account_id(router):
    result = asyncio.run(
        router.route_command(
            account_id="",
            command={
                "command_type": "BUY",
            },
        )
    )

    assert result.success is False
    assert result.message == "Account ID is required."


def test_rejects_invalid_command_type(router):
    result = asyncio.run(
        router.route_command(
            account_id="account-1",
            command={
                "command_type": "INVALID",
            },
        )
    )

    assert result.success is False
    assert "Unsupported command type" in result.message


def test_rejects_account_without_worker(router, database):
    database.get_account.return_value = {
        "id": "account-1",
        "worker_id": None,
    }

    result = asyncio.run(
        router.route_command(
            account_id="account-1",
            command={
                "command_type": "BUY",
            },
        )
    )

    assert result.success is False
    assert result.message == "Account is not assigned to an MT5 worker."


def test_rejects_missing_worker(router, worker_registry):
    worker_registry.get_worker.return_value = None

    result = asyncio.run(
        router.route_command(
            account_id="account-1",
            command={
                "command_type": "BUY",
            },
        )
    )

    assert result.success is False
    assert result.message == "Assigned MT5 worker not found."


def test_rejects_inactive_worker(router, worker_registry):
    worker_registry.get_worker.return_value = {
        "id": "worker-1",
        "status": "OFFLINE",
    }

    result = asyncio.run(
        router.route_command(
            account_id="account-1",
            command={
                "command_type": "BUY",
            },
        )
    )

    assert result.success is False
    assert "not active" in result.message


def test_requires_worker_shared_secret(router, monkeypatch):
    monkeypatch.setenv("WORKER_API_URL", "https://worker.example.com")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "")

    result = asyncio.run(
        router.route_command(
            account_id="account-1",
            command={
                "command_type": "BUY",
            },
        )
    )

    assert result.success is False
    assert "WORKER_SHARED_SECRET" in result.message


def test_routes_buy_command_to_assigned_worker(router, monkeypatch):
    monkeypatch.setenv("WORKER_API_URL", "https://worker.example.com")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "test-secret")

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "order_ref": "order-123",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers

            return FakeResponse()

    monkeypatch.setattr(
        "execution.order_router.httpx.AsyncClient",
        FakeClient,
    )

    result = asyncio.run(
        router.route_command(
            account_id="account-1",
            command={
                "command_type": "BUY",
                "symbol": "XAUUSDm",
                "volume": 0.04,
                "stop_loss": 3297.00,
                "take_profit": 3303.00,
                "comment": "BALANCED-SCALP-1 [BOSSMODE99]",
            },
        )
    )

    assert result.success is True
    assert result.worker_id == "worker-1"
    assert result.order_ref == "order-123"
    assert captured["url"] == (
        "https://worker.example.com/workers/worker-1/commands"
    )
    assert captured["json"]["account_id"] == "account-1"
    assert captured["json"]["worker_id"] == "worker-1"
    assert captured["headers"]["X-Worker-Secret"] == "test-secret"


def test_routes_sell_command_to_assigned_worker(router, monkeypatch):
    monkeypatch.setenv("WORKER_API_URL", "https://worker.example.com")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "test-secret")

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "order_ref": "order-456",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers

            return FakeResponse()

    monkeypatch.setattr(
        "execution.order_router.httpx.AsyncClient",
        FakeClient,
    )

    result = asyncio.run(
        router.route_command(
            account_id="account-1",
            command={
                "command_type": "SELL",
                "symbol": "XAUUSDm",
                "volume": 0.04,
                "stop_loss": 3303.00,
                "take_profit": 3297.00,
                "comment": "BALANCED-SCALP-1 [BOSSMODE99]",
            },
        )
    )

    assert result.success is True
    assert result.worker_id == "worker-1"
    assert result.order_ref == "order-456"
    assert captured["json"]["command_type"] == "SELL"


def test_routes_close_basket_command_to_assigned_worker(
    router,
    monkeypatch,
):
    monkeypatch.setenv("WORKER_API_URL", "https://worker.example.com")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "test-secret")

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "order_ref": "basket-close-789",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers

            return FakeResponse()

    monkeypatch.setattr(
        "execution.order_router.httpx.AsyncClient",
        FakeClient,
    )

    result = asyncio.run(
        router.route_command(
            account_id="account-1",
            command={
                "command_type": "CLOSE_BASKET",
                "symbol": "XAUUSDm",
            },
        )
    )

    assert result.success is True
    assert result.worker_id == "worker-1"
    assert result.order_ref == "basket-close-789"
    assert captured["json"]["command_type"] == "CLOSE_BASKET"
