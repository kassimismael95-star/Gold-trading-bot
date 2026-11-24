from core.risk_manager import RiskManager


risk_manager = RiskManager()


def test_small_account_first_lot_is_0_01():
    plan = risk_manager.calculate_video_dynamic_burst(
        equity=5.00,
        balance=5.00,
        confidence_score=6,
    )

    assert plan.first_lot == 0.01
    assert plan.max_positions == 3
    assert plan.basket_profit_target == 0.50


def test_small_account_low_confidence_has_two_positions():
    plan = risk_manager.calculate_video_dynamic_burst(
        equity=5.00,
        balance=5.00,
        confidence_score=3,
    )

    assert plan.first_lot == 0.01
    assert plan.max_positions == 2
    assert plan.basket_profit_target == 0.50


def test_25_usd_account_uses_correct_first_lot():
    plan = risk_manager.calculate_video_dynamic_burst(
        equity=30.00,
        balance=30.00,
        confidence_score=7,
    )

    assert plan.first_lot == 0.03
    assert plan.max_positions == 7
    assert plan.basket_profit_target == 2.00


def test_100_usd_account_uses_correct_first_lot():
    plan = risk_manager.calculate_video_dynamic_burst(
        equity=120.00,
        balance=120.00,
        confidence_score=6,
    )

    assert plan.first_lot == 0.04
    assert plan.max_positions == 9
    assert plan.basket_profit_target == 4.00


def test_large_account_uses_correct_first_lot():
    plan = risk_manager.calculate_video_dynamic_burst(
        equity=30000.00,
        balance=30000.00,
        confidence_score=6,
    )

    assert plan.first_lot == 4.00
    assert plan.max_positions == 18
    assert plan.basket_profit_target == 1500.00


def test_added_position_lot_includes_original_bonus():
    lot = risk_manager.calculate_added_position_lot(
        equity=100.00,
        balance=100.00,
        confidence_score=6,
        position_number=3,
    )

    assert lot == 0.05


def test_added_position_lot_has_no_bonus_below_25_usd():
    lot = risk_manager.calculate_added_position_lot(
        equity=10.00,
        balance=10.00,
        confidence_score=6,
        position_number=5,
    )

    assert lot == 0.01


def test_dynamic_tp_sl_buy_direction():
    plan = risk_manager.calculate_dynamic_tp_sl(
        direction="BUY",
        entry_price=3300.00,
        current_spread_pips=10.0,
        confidence_score=6,
        position_number=1,
        recent_price_movement=0.20,
    )

    assert plan.direction == "BUY"
    assert plan.stop_loss < 3300.00
    assert plan.take_profit > 3300.00
    assert plan.stop_loss_distance >= 1.50
    assert plan.stop_loss_distance <= 3.00
    assert plan.take_profit_distance >= 1.80
    assert plan.take_profit_distance <= 3.50


def test_dynamic_tp_sl_sell_direction():
    plan = risk_manager.calculate_dynamic_tp_sl(
        direction="SELL",
        entry_price=3300.00,
        current_spread_pips=10.0,
        confidence_score=6,
        position_number=1,
        recent_price_movement=0.20,
    )

    assert plan.direction == "SELL"
    assert plan.stop_loss > 3300.00
    assert plan.take_profit < 3300.00
    assert plan.stop_loss_distance >= 1.50
    assert plan.stop_loss_distance <= 3.00
    assert plan.take_profit_distance >= 1.80
    assert plan.take_profit_distance <= 3.50


def test_basket_profit_target_closes_basket():
    should_close = risk_manager.should_close_basket_by_profit(
        basket_profit=4.10,
        equity=120.00,
        balance=120.00,
        confidence_score=6,
    )

    assert should_close is True


def test_basket_below_profit_target_does_not_close():
    should_close = risk_manager.should_close_basket_by_profit(
        basket_profit=3.00,
        equity=120.00,
        balance=120.00,
        confidence_score=6,
    )

    assert should_close is False


def test_35_percent_drawdown_circuit_breaker_triggers():
    should_close = risk_manager.should_trigger_drawdown_circuit_breaker(
        balance=100.00,
        net_floating_profit=-36.00,
    )

    assert should_close is True


def test_35_percent_drawdown_circuit_breaker_does_not_trigger():
    should_close = risk_manager.should_trigger_drawdown_circuit_breaker(
        balance=100.00,
        net_floating_profit=-34.00,
    )

    assert should_close is False


def test_drawdown_circuit_breaker_ignores_small_balance():
    should_close = risk_manager.should_trigger_drawdown_circuit_breaker(
        balance=5.00,
        net_floating_profit=-10.00,
    )

    assert should_close is False


def test_add_position_requires_positive_basket_profit():
    can_add = risk_manager.can_add_position(
        basket_profit=-1.00,
        price_progress=0.20,
        current_spread_pips=10.0,
        free_margin=100.00,
        open_position_count=1,
        equity=100.00,
        balance=100.00,
        confidence_score=6,
    )

    assert can_add is False


def test_add_position_requires_price_progress():
    can_add = risk_manager.can_add_position(
        basket_profit=1.00,
        price_progress=0.10,
        current_spread_pips=10.0,
        free_margin=100.00,
        open_position_count=1,
        equity=100.00,
        balance=100.00,
        confidence_score=6,
    )

    assert can_add is False


def test_add_position_requires_low_spread():
    can_add = risk_manager.can_add_position(
        basket_profit=1.00,
        price_progress=0.20,
        current_spread_pips=40.0,
        free_margin=100.00,
        open_position_count=1,
        equity=100.00,
        balance=100.00,
        confidence_score=6,
    )

    assert can_add is False


def test_add_position_requires_free_margin():
    can_add = risk_manager.can_add_position(
        basket_profit=1.00,
        price_progress=0.20,
        current_spread_pips=10.0,
        free_margin=0.00,
        open_position_count=1,
        equity=100.00,
        balance=100.00,
        confidence_score=6,
    )

    assert can_add is False


def test_add_position_stops_at_hard_limit():
    can_add = risk_manager.can_add_position(
        basket_profit=1.00,
        price_progress=0.20,
        current_spread_pips=10.0,
        free_margin=100.00,
        open_position_count=18,
        equity=100.00,
        balance=100.00,
        confidence_score=6,
    )

    assert can_add is False
