import unittest

from core.signal_engine import MicroMomentumTracker


class TestSignalEngine(unittest.TestCase):
    def test_not_enough_ticks_returns_default_buy(self):
        tracker = MicroMomentumTracker()

        tracker.record_tick(2300.00)
        tracker.record_tick(2300.01)

        direction, score = tracker.evaluate()

        self.assertEqual(direction, "BUY")
        self.assertEqual(score, 6)

    def test_rising_prices_return_buy(self):
        tracker = MicroMomentumTracker()

        prices = [
            2300.00,
            2300.05,
            2300.10,
            2300.20,
            2300.30
        ]

        for price in prices:
            tracker.record_tick(price)

        direction, score = tracker.evaluate()

        self.assertEqual(direction, "BUY")
        self.assertGreater(score, 0)

    def test_falling_prices_return_sell(self):
        tracker = MicroMomentumTracker()

        prices = [
            2300.30,
            2300.20,
            2300.10,
            2300.05,
            2300.00
        ]

        for price in prices:
            tracker.record_tick(price)

        direction, score = tracker.evaluate()

        self.assertEqual(direction, "SELL")
        self.assertLess(score, 0)

    def test_score_is_limited_to_positive_ten(self):
        tracker = MicroMomentumTracker()

        prices = [
            2300.00,
            2301.00,
            2302.00,
            2303.00,
            2304.00,
            2305.00
        ]

        for price in prices:
            tracker.record_tick(price)

        direction, score = tracker.evaluate()

        self.assertEqual(direction, "BUY")
        self.assertLessEqual(score, 10)

    def test_score_is_limited_to_negative_ten(self):
        tracker = MicroMomentumTracker()

        prices = [
            2305.00,
            2304.00,
            2303.00,
            2302.00,
            2301.00,
            2300.00
        ]

        for price in prices:
            tracker.record_tick(price)

        direction, score = tracker.evaluate()

        self.assertEqual(direction, "SELL")
        self.assertGreaterEqual(score, -10)

    def test_recent_movement_returns_absolute_value(self):
        tracker = MicroMomentumTracker()

        tracker.record_tick(2300.00)
        tracker.record_tick(2300.10)
        tracker.record_tick(2300.30)

        movement = tracker.recent_movement()

        self.assertEqual(movement, 0.30)

    def test_recent_movement_returns_zero_without_enough_ticks(self):
        tracker = MicroMomentumTracker()

        tracker.record_tick(2300.00)

        movement = tracker.recent_movement()

        self.assertEqual(movement, 0.0)


if __name__ == "__main__":
    unittest.main()
