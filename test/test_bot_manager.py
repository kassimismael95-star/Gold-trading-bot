from unittest.mock import MagicMock

import pytest

from bot_manager import BotManager


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_order_router():
    return MagicMock()


@pytest.fixture
def bot_manager(mock_db, mock_order_router):
    return BotManager(
        db=mock_db,
        order_router=mock_order_router,
    )


def make_tick(
    bid: float,
    ask: float,
) -> dict:
    return {
        "bid": bid,
        "ask": ask,
    }


def make_bot_config(
    account_id: str = "account-1",
    license_key: str = "BOSSMODE99",
    max_positions: int = 18,
) -> dict:
    return {
        "account_id": account_id,
        "license_key": license_key,
        "max_positions": max_positions,
        "add_position_move_usd": 0.15,
        "multi_scalp_cooldown_seconds": 3,
        "sl_base_usd": 2.00,
        "tp_base_usd": 2.20,
        "sl_min_usd": 1.50,
        "sl_max_usd": 3.00,
        "tp_min_usd": 1.80,
        "tp_max_usd": 3.50,
        "poll_latency_delay": 0.05,
        "burst_spacing_delay": 0.08,
        "max_allowed_spread_pips": 35.0,
    }


def test_momentum_tracker_returns_buy_with_few_ticks(bot_manager):
    result = bot_manager.evaluate_momentum(
        ticks=[],
    )

    assert result["direction"] == "BUY"
    assert result["confidence"] == 6


def test_momentum_tracker_clamps_score(bot_manager):
    ticks = []

    for index in range(20):
        ticks.append(
            make_tick(
                bid=3300.00 + index,
                ask=3300.10 + index,
            )
        )

    result = bot_manager.evaluate_momentum(
        ticks=ticks,
    )

    assert result["score"] <= 10
    assert result["score"] >= -10


def test_momentum_tracker_buy_when_score_positive(bot_manager):
    ticks = []

    for index in range(20):
        ticks.append(
            make_tick(
                bid=3300.00 + index,
                ask=3300.10 + index,
            )
        )

    result = bot_manager.evaluate_momentum(
        ticks=ticks,
    )

    if result["score"] >= 0:
        assert result["direction"] == "BUY"

    else:
        assert result["direction"] == "SELL"


def test_momentum_tracker_sell_when_score_negative(bot_manager):
    ticks = []

    for index in range(20):
        ticks.append(
            make_tick(
                bid=3320.00 - index,
                ask=3320.10 - index,
            )
        )

    result = bot_manager.evaluate_momentum(
        ticks=ticks,
    )

    if result["score"] >= 0:
        assert result["direction"] == "BUY"

    else:
        assert result["direction"] == "SELL"


def test_rejects_order_when_spread_too_high(bot_manager):
    bot_config = make_bot_config()

    tick = make_tick(
        bid=3300.00,
        ask=3310.00,
    )

    result = bot_manager.validate_spread(
        bot_config=bot_config,
        tick=tick,
    )

    assert result["success"] is False
    assert "Spread too high" in result["message"]


def test_allows_order_when_spread_acceptable(bot_manager):
    bot_config = make_bot_config()

    tick = make_tick(
        bid=3300.00,
        ask=3300.10,
    )

    result = bot_manager.validate_spread(
        bot_config=bot_config,
        tick=tick,
    )

    assert result["success"] is True


def test_rejects_order_when_max_positions_reached(bot_manager):
    bot_config = make_bot_config()

    open_positions = []

    for index in range(18):
        open_positions.append(
            {
                "ticket": 100000 + index,
                "symbol": "XAUUSDm",
                "type": "BUY",
                "volume": 0.01,
            }
        )

    result = bot_manager.check_position_limit(
        bot_config=bot_config,
        open_positions=open_positions,
    )

    assert result["success"] is False
    assert "Maximum positions reached" in result["message"]


def test_allows_order_when_below_max_positions(bot_manager):
    bot_config = make_bot_config()

    open_positions = []

    for index in range(17):
        open_positions.append(
            {
                "ticket": 100000 + index,
                "symbol": "XAUUSDm",
                "type": "BUY",
                "volume": 0.01,
            }
        )

    result = bot_manager.check_position_limit(
        bot_config=bot_config,
        open_positions=open_positions,
    )

    assert result["success"] is True


def test_calculates_dynamic_sl_and_tp(bot_manager):
    bot_config = make_bot_config()

    result = bot_manager.calculate_dynamic_sl_tp(
        bot_config=bot_config,
        direction="BUY",
        entry_price=3300.00,
        position_number=1,
    )

    assert result["stop_loss"] < 3300.00
    assert result["take_profit"] > 3300.00


def test_calculates_dynamic_sl_and_tp_for_sell(bot_manager):
    bot_config = make_bot_config()

    result = bot_manager.calculate_dynamic_sl_tp(
        bot_config=bot_config,
        direction="SELL",
        entry_price=3300.00,
        position_number=1,
    )

    assert result["stop_loss"] > 3300.00
    assert result["take_profit"] < 3300.00


def test_calculates_added_lot_tier(bot_manager):
    bot_config = make_bot_config()

    result = bot_manager.calculate_added_lot_tier(
        bot_config=bot_config,
        position_number=1,
    )

    assert result["volume"] > 0


def test_calculates_burst_spacing_delay(bot_manager):
    bot_config = make_bot_config()

    result = bot_manager.calculate_burst_spacing_delay(
        bot_config=bot_config,
        position_number=1,
    )

    assert result["delay"] >= 0
