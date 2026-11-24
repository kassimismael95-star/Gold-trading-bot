from unittest.mock import MagicMock

import pytest

from worker.command_executor import CommandExecutor
from worker.mt5_client import MT5Client


@pytest.fixture
def mt5_client():
    return MT5Client()


@pytest.fixture
def command_executor(mt5_client):
    return CommandExecutor(mt5_client=mt5_client)


def make_command(
    command_type: str,
    account_id: str = "account-1",
    worker_id: str = "worker-1",
    symbol: str = "XAUUSDm",
    volume: float = 0.01,
    stop_loss: float = 3297.00,
    take_profit: float = 3303.00,
    comment: str = "BALANCED-SCALP-1 [BOSSMODE99]",
) -> dict:
    return {
        "command_type": command_type,
        "account_id": account_id,
        "worker_id": worker_id,
        "symbol": symbol,
        "volume": volume,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "comment": comment,
    }


def test_rejects_unsupported_command(command_executor):
    result = command_executor.execute(
        make_command("INVALID")
    )

    assert result.success is False
    assert "Unsupported command type" in result.message


def test_requires_account_id(command_executor):
    command = make_command("BUY")

    command["account_id"] = ""

    result = command_executor.execute(command)

    assert result.success is False
    assert "Account ID is required" in result.message


def test_requires_worker_id(command_executor):
    command = make_command("BUY")

    command["worker_id"] = ""

    result = command_executor.execute(command)

    assert result.success is False
    assert "Worker ID is required" in result.message


def test_rejects_zero_volume(command_executor):
    command = make_command("BUY")

    command["volume"] = 0

    with patch_open_market_order(command_executor):
        result = command_executor.execute(command)

    assert result.success is False
    assert "Volume must be greater than zero" in result.message


def test_rejects_missing_stop_loss(command_executor):
    command = make_command("BUY")

    command["stop_loss"] = 0

    with patch_open_market_order(command_executor):
        result = command_executor.execute(command)

    assert result.success is False
    assert "Stop loss and take profit are required" in result.message


def test_rejects_missing_take_profit(command_executor):
    command = make_command("BUY")

    command["take_profit"] = 0

    with patch_open_market_order(command_executor):
        result = command_executor.execute(command)

    assert result.success is False
    assert "Stop loss and take profit are required" in result.message


def test_executes_buy_command(command_executor):
    command = make_command("BUY")

    mock_open = MagicMock(
        return_value={
            "success": True,
            "message": "BUY order opened on XAUUSDm with 0.01 lots.",
            "order_ticket": 123456,
            "deal_ticket": 789012,
            "price": 3300.10,
        }
    )

    command_executor.mt5_client.open_market_order = mock_open

    result = command_executor.execute(command)

    assert result.success is True
    assert result.command_type == "BUY"
    assert result.response["order_ticket"] == 123456

    mock_open.assert_called_once_with(
        symbol="XAUUSDm",
        direction="BUY",
        volume=0.01,
        stop_loss=3297.00,
        take_profit=3303.00,
        comment="BALANCED-SCALP-1 [BOSSMODE99]",
    )


def test_executes_sell_command(command_executor):
    command = make_command("SELL")

    mock_open = MagicMock(
        return_value={
            "success": True,
            "message": "SELL order opened on XAUUSDm with 0.01 lots.",
            "order_ticket": 123457,
            "deal_ticket": 789013,
            "price": 3299.90,
        }
    )

    command_executor.mt5_client.open_market_order = mock_open

    result = command_executor.execute(command)

    assert result.success is True
    assert result.command_type == "SELL"
    assert result.response["order_ticket"] == 123457

    mock_open.assert_called_once_with(
        symbol="XAUUSDm",
        direction="SELL",
        volume=0.01,
        stop_loss=3297.00,
        take_profit=3303.00,
        comment="BALANCED-SCALP-1 [BOSSMODE99]",
    )


def test_executes_close_basket(command_executor):
    command = make_command("CLOSE_BASKET")

    mock_close_all = MagicMock(
        return_value={
            "success": True,
            "message": "Closed 3/3 positions.",
            "closed_count": 3,
            "errors": [],
        }
    )

    command_executor.mt5_client.close_all_positions = mock_close_all

    result = command_executor.execute(command)

    assert result.success is True
    assert result.command_type == "CLOSE_BASKET"
    assert result.response["closed_count"] == 3

    mock_close_all.assert_called_once_with("XAUUSDm")


def test_close_basket_failure_is_returned(command_executor):
    command = make_command("CLOSE_BASKET")

    mock_close_all = MagicMock(
        return_value={
            "success": False,
            "message": "Closed 2/3 positions.",
            "closed_count": 2,
            "errors": [
                "MT5 close rejected."
            ],
        }
    )

    command_executor.mt5_client.close_all_positions = mock_close_all

    result = command_executor.execute(command)

    assert result.success is False
    assert result.command_type == "CLOSE_BASKET"
    assert result.response["closed_count"] == 2


def patch_open_market_order(command_executor):
    command_executor.mt5_client.open_market_order = MagicMock(
        return_value={
            "success": False,
            "message": "Order should not be sent.",
        }
  )
