import os
from unittest.mock import MagicMock, patch

import pytest

os_environ = {
    "SECRET_KEY": "test-secret-key",
    "DATABASE_URL": "sqlite:///:memory:",
    "ENABLE_LIVE_TRADING": "true",
    "LIVE_TRADING_AUTHORIZED": "false",
}

with patch.dict("os.environ", os_environ):
    from app import app
    from live_trading_gate import LiveTradingGate


@pytest.fixture
def client():
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client


@pytest.fixture
def live_trading_gate():
    return LiveTradingGate(
        enable_live_trading=True,
        live_trading_authorized=False,
    )


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


def test_live_trading_flag_is_enabled():
    from app import ENABLE_LIVE_TRADING

    assert ENABLE_LIVE_TRADING is True


def test_live_trading_gate_blocks_when_not_authorized(live_trading_gate):
    result = live_trading_gate.validate(
        command=make_command(),
    )

    assert result["success"] is False
    assert "Live trading is not authorized" in result["message"]


def test_live_trading_gate_allows_when_authorized():
    gate = LiveTradingGate(
        enable_live_trading=True,
        live_trading_authorized=True,
    )

    result = gate.validate(
        command=make_command(),
    )

    assert result["success"] is True
    assert result["message"] == "Live trading is authorized."


def test_live_trading_gate_blocks_when_disabled():
    gate = LiveTradingGate(
        enable_live_trading=False,
        live_trading_authorized=True,
    )

    result = gate.validate(
        command=make_command(),
    )

    assert result["success"] is False
    assert "Live trading is disabled" in result["message"]


def test_live_trading_gate_requires_command(live_trading_gate):
    result = live_trading_gate.validate(
        command=None,
    )

    assert result["success"] is False
    assert "Command is required" in result["message"]


def test_live_trading_gate_requires_account_id(live_trading_gate):
    command = make_command()

    command["account_id"] = ""

    result = live_trading_gate.validate(
        command=command,
    )

    assert result["success"] is False
    assert "Account ID is required" in result["message"]


def test_live_trading_gate_requires_symbol(live_trading_gate):
    command = make_command()

    command["symbol"] = ""

    result = live_trading_gate.validate(
        command=command,
    )

    assert result["success"] is False
    assert "Symbol is required" in result["message"]


def test_live_trading_gate_requires_volume(live_trading_gate):
    command = make_command()

    command["volume"] = 0

    result = live_trading_gate.validate(
        command=command,
    )

    assert result["success"] is False
    assert "Volume must be greater than zero" in result["message"]


def test_live_trading_gate_requires_stop_loss(live_trading_gate):
    command = make_command()

    command["stop_loss"] = 0

    result = live_trading_gate.validate(
        command=command,
    )

    assert result["success"] is False
    assert "Stop loss and take profit are required" in result["message"]


def test_live_trading_gate_requires_take_profit(live_trading_gate):
    command = make_command()

    command["take_profit"] = 0

    result = live_trading_gate.validate(
        command=command,
    )

    assert result["success"] is False
    assert "Stop loss and take profit are required" in result["message"]


def test_live_trading_gate_allows_close_basket():
    gate = LiveTradingGate(
        enable_live_trading=True,
        live_trading_authorized=True,
    )

    command = {
        "command_type": "CLOSE_BASKET",
        "account_id": "account-1",
        "symbol": "XAUUSDm",
    }

    result = gate.validate(
        command=command,
    )

    assert result["success"] is True
    assert result["message"] == "Live trading is authorized."


def test_live_trading_gate_blocks_close_basket_when_not_authorized(live_trading_gate):
    command = {
        "command_type": "CLOSE_BASKET",
        "account_id": "account-1",
        "symbol": "XAUUSDm",
    }

    result = live_trading_gate.validate(
        command=command,
    )

    assert result["success"] is False
    assert "Live trading is not authorized" in result["message"]


def test_api_command_requires_authorization(client):
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
