from unittest.mock import MagicMock, patch

import pytest

from worker.mt5_client import MT5Client


@pytest.fixture
def mt5_client():
    return MT5Client()


def test_initialize_failure_returns_not_connected(mt5_client):
    with patch(
        "worker.mt5_client.mt5.initialize",
        return_value=False,
    ):
        result = mt5_client.initialize()

    assert result.connected is False
    assert "initialization failed" in result.message.lower()


def test_initialize_success_sets_initialized(mt5_client):
    with patch(
        "worker.mt5_client.mt5.initialize",
        return_value=True,
    ):
        result = mt5_client.initialize()

    assert result.connected is True
    assert mt5_client.initialized is True
    assert "initialized" in result.message.lower()


def test_login_requires_initialization(mt5_client):
    with patch(
        "worker.mt5_client.mt5.initialize",
        return_value=False,
    ):
        result = mt5_client.login(
            login="123456",
            password="password",
            server="Exness-MT5Real",
        )

    assert result.connected is False
    assert "initialization failed" in result.message.lower()


def test_login_failure_returns_not_connected(mt5_client):
    mt5_client.initialized = True

    with patch(
        "worker.mt5_client.mt5.login",
        return_value=False,
    ):
        result = mt5_client.login(
            login="123456",
            password="wrong-password",
            server="Exness-MT5Real",
        )

    assert result.connected is False
    assert "login failed" in result.message.lower()


def test_login_success_returns_account_information(mt5_client):
    mt5_client.initialized = True

    account_info = MagicMock()

    account_info.login = 123456
    account_info.server = "Exness-MT5Real"
    account_info.balance = 100.00
    account_info.equity = 100.00
    account_info.margin_free = 90.00
    account_info.margin_level = 1000.00

    with patch(
        "worker.mt5_client.mt5.login",
        return_value=True,
    ):
        with patch(
            "worker.mt5_client.mt5.account_info",
            return_value=account_info,
        ):
            result = mt5_client.login(
                login="123456",
                password="password",
                server="Exness-MT5Real",
            )

    assert result.connected is True
    assert result.account_info["balance"] == 100.00
    assert result.account_info["equity"] == 100.00
    assert result.account_info["free_margin"] == 90.00


def test_symbol_resolution_prefers_requested_symbol(mt5_client):
    symbol_info = MagicMock()
    symbol_info.visible = True

    tick = MagicMock()
    tick.bid = 3300.00
    tick.ask = 3300.10

    with patch(
        "worker.mt5_client.mt5.symbol_info",
        return_value=symbol_info,
    ):
        with patch(
            "worker.mt5_client.mt5.symbol_info_tick",
            return_value=tick,
        ):
            resolved = mt5_client.resolve_gold_symbol("XAUUSDm")

    assert resolved == "XAUUSDm"
    assert mt5_client.active_symbol == "XAUUSDm"


def test_symbol_resolution_falls_back_to_xauusd(mt5_client):
    requested_symbol_info = None
    xauusd_symbol_info = MagicMock()
    xauusd_symbol_info.visible = True

    tick = MagicMock()
    tick.bid = 3300.00
    tick.ask = 3300.10

    def symbol_info_side_effect(symbol):
        if symbol == "XAUUSDm":
            return requested_symbol_info

        if symbol == "XAUUSD":
            return xauusd_symbol_info

        return None

    def symbol_tick_side_effect(symbol):
        if symbol == "XAUUSD":
            return tick

        return None

    with patch(
        "worker.mt5_client.mt5.symbol_info",
        side_effect=symbol_info_side_effect,
    ):
        with patch(
            "worker.mt5_client.mt5.symbol_info_tick",
            side_effect=symbol_tick_side_effect,
        ):
            resolved = mt5_client.resolve_gold_symbol("XAUUSDm")

    assert resolved == "XAUUSD"
    assert mt5_client.active_symbol == "XAUUSD"


def test_get_symbol_tick_returns_bid_and_ask(mt5_client):
    tick = MagicMock()
    tick.bid = 3300.00
    tick.ask = 3300.10

    with patch(
        "worker.mt5_client.mt5.symbol_info_tick",
        return_value=tick,
    ):
        result = mt5_client.get_symbol_tick("XAUUSDm")

    assert result == {
        "bid": 3300.00,
        "ask": 3300.10,
    }


def test_get_symbol_tick_returns_none_for_invalid_prices(mt5_client):
    tick = MagicMock()
    tick.bid = 0
    tick.ask = 0

    with patch(
        "worker.mt5_client.mt5.symbol_info_tick",
        return_value=tick,
    ):
        result = mt5_client.get_symbol_tick("XAUUSDm")

    assert result is None


def test_open_market_order_rejects_invalid_direction(mt5_client):
    result = mt5_client.open_market_order(
        symbol="XAUUSDm",
        direction="INVALID",
        volume=0.01,
        stop_loss=3297.00,
        take_profit=3303.00,
        comment="BALANCED-SCALP-1 [BOSSMODE99]",
    )

    assert result["success"] is False
    assert "BUY or SELL" in result["message"]


def test_open_market_order_rejects_missing_price(mt5_client):
    with patch(
        "worker.mt5_client.mt5.symbol_info_tick",
        return_value=None,
    ):
        result = mt5_client.open_market_order(
            symbol="XAUUSDm",
            direction="BUY",
            volume=0.01,
            stop_loss=3297.00,
            take_profit=3303.00,
            comment="BALANCED-SCALP-1 [BOSSMODE99]",
        )

    assert result["success"] is False
    assert "No valid market price" in result["message"]


def test_close_all_positions_with_no_positions(mt5_client):
    with patch(
        "worker.mt5_client.mt5.positions_get",
        return_value=(),
    ):
        result = mt5_client.close_all_positions("XAUUSDm")

    assert result["success"] is True
    assert result["closed_count"] == 0
    assert "No open positions" in result["message"]
