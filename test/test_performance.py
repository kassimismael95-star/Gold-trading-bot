import time
from unittest.mock import MagicMock

import pytest

from bot_manager import BotManager
from order_router import OrderRouter


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


@pytest.fixture
def order_router(mock_db, mock_worker_registry):
    return OrderRouter(
        db=mock_db,
        worker_registry=mock_worker_registry,
    )


@pytest.fixture
def mock_worker_registry():
    return MagicMock()


def make_tick(
    bid: float,
    ask: float,
) -> dict:
    return {
        "bid": bid,
        "ask": ask,
    }


def make_bot_config() -> dict:
    return {
        "account_id": "account-1",
        "license_key": "BOSSMODE99",
        "max_positions": 18,
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


def test_poll_latency_delay_is_preserved(bot_manager):
    bot_config = make_bot_config()

    result = bot_manager.calculate_poll_latency_delay(
        bot_config=bot_config,
    )

    assert result["delay"] == 0.05


def test_burst_spacing_delay_is_preserved(bot_manager):
    bot_config = make_bot_config()

    result = bot_manager.calculate_burst_spacing_delay(
        bot_config=bot_config,
        position_number=1,
    )

    assert result["delay"] >= 0.08


def test_momentum_calculation_is_fast(bot_manager):
    ticks = []

    for index in range(20):
        ticks.append(
            make_tick(
                bid=3300.00 + index,
                ask=3300.10 + index,
            )
        )

    start = time.perf_counter()

    for _ in range(100):
        bot_manager.evaluate_momentum(
            ticks=ticks,
        )

    end = time.perf_counter()

    elapsed = end - start

    assert elapsed < 1.0


def test_spread_validation_is_fast(bot_manager):
    bot_config = make_bot_config()

    tick = make_tick(
        bid=3300.00,
        ask=3300.10,
    )

    start = time.perf_counter()

    for _ in range(100):
        bot_manager.validate_spread(
            bot_config=bot_config,
            tick=tick,
        )

    end = time.perf_counter()

    elapsed = end - start

    assert elapsed < 1.0


def test_position_limit_check_is_fast(bot_manager):
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

    start = time.perf_counter()

    for _ in range(100):
        bot_manager.check_position_limit(
            bot_config=bot_config,
            open_positions=open_positions,
        )

    end = time.perf_counter()

    elapsed = end - start

    assert elapsed < 1.0


def test_dynamic_sl_tp_calculation_is_fast(bot_manager):
    bot_config = make_bot_config()

    start = time.perf_counter()

    for _ in range(100):
        bot_manager.calculate_dynamic_sl_tp(
            bot_config=bot_config,
            direction="BUY",
            entry_price=3300.00,
            position_number=1,
        )

    end = time.perf_counter()

    elapsed = end - start

    assert elapsed < 1.0


def test_added_lot_tier_calculation_is_fast(bot_manager):
    bot_config = make_bot_config()

    start = time.perf_counter()

    for _ in range(100):
        bot_manager.calculate_added_lot_tier(
            bot_config=bot_config,
            position_number=1,
        )

    end = time.perf_counter()

    elapsed = end - start

    assert elapsed < 1.0


def test_command_routing_is_fast(order_router, mock_db, mock_worker_registry):
    mock_db.get_recent_command_by_signature.return_value = None
    mock_db.create_command.return_value = MagicMock()

    worker = MagicMock()

    worker.id = "worker-1"
    worker.worker_url = "https://worker-1.example.com"

    mock_worker_registry.assign_worker.return_value = {
        "success": True,
        "worker_id": "worker-1",
        "worker_url": worker.worker_url,
    }

    start = time.perf_counter()

    for _ in range(100):
        order_router.route_command(
            make_command()
        )

    end = time.perf_counter()

    elapsed = end - start

    assert elapsed < 1.0


def test_command_routing_preserves_original_command(order_router, mock_db, mock_worker_registry):
    mock_db.get_recent_command_by_signature.return_value = None
    mock_db.create_command.return_value = MagicMock()

    worker = MagicMock()

    worker.id = "worker-1"
    worker.worker_url = "https://worker-1.example.com"

    mock_worker_registry.assign_worker.return_value = {
        "success": True,
        "worker_id": "worker-1",
        "worker_url": worker.worker_url,
    }

    result = order_router.route_command(
        make_command()
    )

    assert result["success"] is True
    assert result["command_type"] == "BUY"
    assert result["worker_id"] == "worker-1"
