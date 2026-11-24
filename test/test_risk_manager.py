import unittest

from core.risk_manager import (
    calculate_video_dynamic_burst,
    calculate_added_position_lot,
    calculate_dynamic_tp_sl,
    MAX_ALLOWED_SPREAD_PIPS
)


class TestRiskManager(unittest.TestCase):
    def test_small_account_uses_minimum_lot(self):
        result = calculate_video_dynamic_burst(
            equity=3.00,
            balance=3.00,
            confidence_score=8
        )

        first_lot, max_positions, basket_target = result

        self.assertEqual(first_lot, 0.01)
        self.assertEqual(max_positions, 2)
        self.assertEqual(basket_target, 0.35)

    def test_low_confidence_reduces_positions(self):
        result = calculate_video_dynamic_burst(
            equity=20.00,
            balance=20.00,
            confidence_score=3
        )

        first_lot, max_positions, basket_target = result

        self.assertEqual(first_lot, 0.02)
        self.assertEqual(max_positions, 3)
        self.assertEqual(basket_target, 1.00)

    def test_high_confidence_allows_more_positions(self):
        result = calculate_video_dynamic_burst(
            equity=20.00,
            balance=20.00,
            confidence_score=8
        )

        first_lot, max_positions, basket_target = result

        self.assertEqual(first_lot, 0.02)
        self.assertEqual(max_positions, 5)
        self.assertEqual(basket_target, 1.00)

    def test_added_position_lot_increases_with_positions(self):
        first_lot = calculate_added_position_lot(
            equity=100.00,
            balance=100.00,
            confidence_score=8,
            position_number=1
        )

        third_lot = calculate_added_position_lot(
            equity=100.00,
            balance=100.00,
            confidence_score=8,
            position_number=3
        )

        self.assertEqual(first_lot, 0.04)
        self.assertEqual(third_lot, 0.05)

    def test_buy_stop_loss_is_below_entry(self):
        result = calculate_dynamic_tp_sl(
            direction="BUY",
            entry_price=2300.00,
            current_spread_pips=10.0,
            confidence_score=8,
            position_number=1,
            recent_price_movement=0.10
        )

        self.assertLess(
            result["stop_loss"],
            2300.00
        )

        self.assertGreater(
            result["take_profit"],
            2300.00
        )

    def test_sell_stop_loss_is_above_entry(self):
        result = calculate_dynamic_tp_sl(
            direction="SELL",
            entry_price=2300.00,
            current_spread_pips=10.0,
            confidence_score=8,
            position_number=1,
            recent_price_movement=0.10
        )

        self.assertGreater(
            result["stop_loss"],
            2300.00
        )

        self.assertLess(
            result["take_profit"],
            2300.00
        )

    def test_take_profit_is_never_below_stop_loss(self):
        result = calculate_dynamic_tp_sl(
            direction="BUY",
            entry_price=2300.00,
            current_spread_pips=MAX_ALLOWED_SPREAD_PIPS,
            confidence_score=1,
            position_number=10,
            recent_price_movement=0.10
        )

        self.assertGreaterEqual(
            result["take_profit_distance"],
            result["stop_loss_distance"]
        )

    def test_reward_risk_ratio_is_calculated(self):
        result = calculate_dynamic_tp_sl(
            direction="BUY",
            entry_price=2300.00,
            current_spread_pips=10.0,
            confidence_score=8,
            position_number=1,
            recent_price_movement=0.10
        )

        expected_ratio = round(
            result["take_profit_distance"]
            / result["stop_loss_distance"],
            2
        )

        self.assertEqual(
            result["reward_risk_ratio"],
            expected_ratio
        )


if __name__ == "__main__":
    unittest.main()
