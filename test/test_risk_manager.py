import unittest

from core.risk_manager import (
    calculate_position_size,
    calculate_stop_loss,
    calculate_take_profit,
    is_risk_within_limits,
    should_block_new_trade
)


class TestRiskManager(unittest.TestCase):
    def test_calculate_position_size_returns_positive_value(self):
        size = calculate_position_size(
            balance=1000.00,
            risk_percent=1.0,
            stop_loss_pips=20.0,
            pip_value=0.10
        )

        self.assertGreater(size, 0)

    def test_calculate_position_size_respects_risk_amount(self):
        size = calculate_position_size(
            balance=1000.00,
            risk_percent=1.0,
            stop_loss_pips=20.0,
            pip_value=0.10
        )

        expected_risk_amount = 10.00
        expected_size = expected_risk_amount / (
            20.0 * 0.10
        )

        self.assertAlmostEqual(
            size,
            expected_size
        )

    def test_calculate_position_size_rejects_invalid_balance(self):
        with self.assertRaises(ValueError):
            calculate_position_size(
                balance=0,
                risk_percent=1.0,
                stop_loss_pips=20.0,
                pip_value=0.10
            )

    def test_calculate_position_size_rejects_invalid_stop_loss(self):
        with self.assertRaises(ValueError):
            calculate_position_size(
                balance=1000.00,
                risk_percent=1.0,
                stop_loss_pips=0,
                pip_value=0.10
            )

    def test_calculate_stop_loss_for_buy(self):
        stop_loss = calculate_stop_loss(
            direction="BUY",
            entry_price=2300.00,
            stop_loss_pips=20.0,
            pip_size=0.01
        )

        self.assertEqual(
            stop_loss,
            2299.80
        )

    def test_calculate_stop_loss_for_sell(self):
        stop_loss = calculate_stop_loss(
            direction="SELL",
            entry_price=2300.00,
            stop_loss_pips=20.0,
            pip_size=0.01
        )

        self.assertEqual(
            stop_loss,
            2300.20
        )

    def test_calculate_take_profit_for_buy(self):
        take_profit = calculate_take_profit(
            direction="BUY",
            entry_price=2300.00,
            take_profit_pips=40.0,
            pip_size=0.01
        )

        self.assertEqual(
            take_profit,
            2300.40
        )

    def test_calculate_take_profit_for_sell(self):
        take_profit = calculate_take_profit(
            direction="SELL",
            entry_price=2300.00,
            take_profit_pips=40.0,
            pip_size=0.01
        )

        self.assertEqual(
            take_profit,
            2299.60
        )

    def test_is_risk_within_limits_returns_true(self):
        result = is_risk_within_limits(
            open_positions=1,
            max_positions=3,
            current_risk_percent=1.0,
            max_risk_percent=2.0,
            daily_loss_percent=1.0,
            max_daily_loss_percent=3.0
        )

        self.assertTrue(result)

    def test_is_risk_within_limits_rejects_too_many_positions(self):
        result = is_risk_within_limits(
            open_positions=4,
            max_positions=3,
            current_risk_percent=1.0,
            max_risk_percent=2.0,
            daily_loss_percent=1.0,
            max_daily_loss_percent=3.0
        )

        self.assertFalse(result)

    def test_is_risk_within_limits_rejects_high_risk(self):
        result = is_risk_within_limits(
            open_positions=1,
            max_positions=3,
            current_risk_percent=3.0,
            max_risk_percent=2.0,
            daily_loss_percent=1.0,
            max_daily_loss_percent=3.0
        )

        self.assertFalse(result)

    def test_is_risk_within_limits_rejects_daily_loss_limit(self):
        result = is_risk_within_limits(
            open_positions=1,
            max_positions=3,
            current_risk_percent=1.0,
            max_risk_percent=2.0,
            daily_loss_percent=4.0,
            max_daily_loss_percent=3.0
        )

        self.assertFalse(result)

    def test_should_block_new_trade_when_daily_loss_exceeded(self):
        result = should_block_new_trade(
            daily_loss_percent=4.0,
            max_daily_loss_percent=3.0
        )

        self.assertTrue(result)

    def test_should_not_block_new_trade_within_daily_loss_limit(self):
        result = should_block_new_trade(
            daily_loss_percent=2.0,
            max_daily_loss_percent=3.0
        )

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
