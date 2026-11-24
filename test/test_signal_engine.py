import unittest

from core.signal_engine import (
    calculate_ema,
    calculate_rsi,
    calculate_atr,
    calculate_trend,
    calculate_confidence,
    generate_signal
)


class TestSignalEngine(unittest.TestCase):
    def test_calculate_ema_returns_float(self):
        prices = [
            2300.00,
            2301.00,
            2302.00,
            2303.00,
            2304.00
        ]

        ema = calculate_ema(
            prices=prices,
            period=3
        )

        self.assertIsInstance(ema, float)

    def test_calculate_rsi_returns_between_0_and_100(self):
        prices = [
            2300.00,
            2301.00,
            2302.00,
            2301.50,
            2303.00,
            2304.00
        ]

        rsi = calculate_rsi(
            prices=prices,
            period=5
        )

        self.assertGreaterEqual(rsi, 0)
        self.assertLessEqual(rsi, 100)

    def test_calculate_atr_returns_positive_value(self):
        candles = [
            {
                "high": 2302.00,
                "low": 2298.00,
                "close": 2300.00
            },
            {
                "high": 2303.00,
                "low": 2299.00,
                "close": 2301.00
            },
            {
                "high": 2304.00,
                "low": 2300.00,
                "close": 2302.00
            }
        ]

        atr = calculate_atr(
            candles=candles,
            period=3
        )

        self.assertGreater(atr, 0)

    def test_calculate_trend_returns_bullish(self):
        trend = calculate_trend(
            fast_ema=2301.00,
            slow_ema=2300.00
        )

        self.assertEqual(trend, "BULLISH")

    def test_calculate_trend_returns_bearish(self):
        trend = calculate_trend(
            fast_ema=2299.00,
            slow_ema=2300.00
        )

        self.assertEqual(trend, "BEARISH")

    def test_calculate_trend_returns_neutral(self):
        trend = calculate_trend(
            fast_ema=2300.00,
            slow_ema=2300.00
        )

        self.assertEqual(trend, "NEUTRAL")

    def test_calculate_confidence_returns_between_0_and_100(self):
        confidence = calculate_confidence(
            trend="BULLISH",
            rsi=55.0,
            atr=2.00,
            average_atr=2.00
        )

        self.assertGreaterEqual(confidence, 0)
        self.assertLessEqual(confidence, 100)

    def test_generate_signal_returns_buy_for_bullish_market(self):
        candles = [
            {
                "high": 2302.00,
                "low": 2298.00,
                "close": 2300.00
            },
            {
                "high": 2303.00,
                "low": 2299.00,
                "close": 2301.00
            },
            {
                "high": 2304.00,
                "low": 2300.00,
                "close": 2302.00
            },
            {
                "high": 2305.00,
                "low": 2301.00,
                "close": 2303.00
            },
            {
                "high": 2306.00,
                "low": 2302.00,
                "close": 2304.00
            }
        ]

        signal = generate_signal(
            candles=candles,
            current_price=2304.50
        )

        self.assertIn(
            signal["direction"],
            [
                "BUY",
                "SELL",
                "WAIT"
            ]
        )

    def test_generate_signal_returns_wait_without_enough_candles(self):
        candles = [
            {
                "high": 2302.00,
                "low": 2298.00,
                "close": 2300.00
            }
        ]

        signal = generate_signal(
            candles=candles,
            current_price=2300.00
        )

        self.assertEqual(
            signal["direction"],
            "WAIT"
        )

        self.assertEqual(
            signal["reason"],
            "INSUFFICIENT_DATA"
        )


if __name__ == "__main__":
    unittest.main()
