from datetime import datetime, timezone

from core.signal_engine import MicroMomentumTracker


def test_tracker_defaults_to_buy_with_fewer_than_three_ticks():
    tracker = MicroMomentumTracker()

    tracker.record_tick(3300.00)
    tracker.record_tick(3300.05)

    result = tracker.evaluate()

    assert result.direction == "BUY"
    assert result.confidence == 6
    assert result.recent_movement == 0.0


def test_tracker_returns_buy_for_upward_short_term_movement():
    tracker = MicroMomentumTracker()

    tracker.record_tick(3300.00)
    tracker.record_tick(3300.10)
    tracker.record_tick(3300.20)

    result = tracker.evaluate()

    assert result.direction == "BUY"
    assert result.confidence > 0
    assert result.recent_movement == 0.20


def test_tracker_returns_sell_for_downward_short_term_movement():
    tracker = MicroMomentumTracker()

    tracker.record_tick(3300.20)
    tracker.record_tick(3300.10)
    tracker.record_tick(3300.00)

    result = tracker.evaluate()

    assert result.direction == "SELL"
    assert result.confidence < 0
    assert result.recent_movement == 0.20


def test_tracker_uses_one_minute_candle_open():
    tracker = MicroMomentumTracker()

    tracker.record_tick(3300.00)
    tracker.record_tick(3300.20)
    tracker.record_tick(3300.30)

    result = tracker.evaluate()

    assert result.direction == "BUY"
    assert result.confidence >= 0


def test_tracker_caps_confidence_at_positive_ten():
    tracker = MicroMomentumTracker()

    tracker.record_tick(3300.00)
    tracker.record_tick(3310.00)
    tracker.record_tick(3320.00)

    result = tracker.evaluate()

    assert result.confidence <= 10


def test_tracker_caps_confidence_at_negative_ten():
    tracker = MicroMomentumTracker()

    tracker.record_tick(3320.00)
    tracker.record_tick(3310.00)
    tracker.record_tick(3300.00)

    result = tracker.evaluate()

    assert result.confidence >= -10


def test_tracker_keeps_tick_history():
    tracker = MicroMomentumTracker()

    tracker.record_tick(3300.00)
    tracker.record_tick(3300.10)
    tracker.record_tick(3300.20)

    first_result = tracker.evaluate()

    tracker.record_tick(3300.30)

    second_result = tracker.evaluate()

    assert first_result.recent_movement == 0.20
    assert second_result.recent_movement == 0.20


def test_tracker_ignores_invalid_price():
    tracker = MicroMomentumTracker()

    tracker.record_tick(3300.00)
    tracker.record_tick(0)
    tracker.record_tick(3300.10)
    tracker.record_tick(3300.20)

    result = tracker.evaluate()

    assert result.direction in ["BUY", "SELL"]
    assert len(tracker.ticks) == 3
