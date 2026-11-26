
"""
Gold Scalper AI
Original momentum strategy foundation.

This module implements the user's original tick and candle
momentum scoring behavior. It does not introduce a new strategy,
additional entry filters, or arbitrary trading thresholds.
"""

from collections import deque
from datetime import datetime, timezone


class MicroMomentumTracker:
    """
    Tracks recent gold prices and calculates the original
    momentum confidence score.
    """

    def __init__(self, max_ticks=20):
        self.prices = deque(maxlen=max_ticks)
        self.candle_open = None
        self.candle_minute = None

    def update(self, price, timestamp=None):
        """
        Add a new price tick and return:
            (direction, confidence_score, recent_movement)

        direction:
            "BUY" or "SELL"

        confidence_score:
            Original momentum score, clamped from -10 to +10.

        recent_movement:
            Absolute price movement between the latest tick
            and the third-last tick.
        """

        try:
            price = float(price)
        except (TypeError, ValueError, OverflowError):
            return self.get_signal()

        if price <= 0:
            return self.get_signal()

        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        timestamp = timestamp.astimezone(timezone.utc)

        current_minute = timestamp.replace(
            second=0,
            microsecond=0,
        )

        # Reset candle open when a new UTC minute begins.
        if self.candle_minute != current_minute:
            self.candle_minute = current_minute
            self.candle_open = price

        if self.candle_open is None:
            self.candle_open = price

        self.prices.append(price)

        return self.get_signal()

    def get_signal(self):
        """
        Calculate the original momentum score from tracked prices.
        """

        if len(self.prices) < 3:
            return "BUY", 6, 0.0

        latest = self.prices[-1]
        third_last = self.prices[-3]
        first = self.prices[0]

        score = 0

        # Original short-term momentum component.
        short_delta = latest - third_last

        if short_delta > 0.05:
            score += 4
        elif short_delta < -0.05:
            score -= 4
        elif short_delta > 0:
            score += 2
        elif short_delta < 0:
            score -= 2

        # Original full-window momentum component.
        full_delta = latest - first

        if full_delta > 0.15:
            score += 3
        elif full_delta < -0.15:
            score -= 3
        elif full_delta > 0:
            score += 1
        elif full_delta < 0:
            score -= 1

        # Original candle momentum component.
        candle_delta = latest - self.candle_open

        if candle_delta > 0.10:
            score += 3
        elif candle_delta < -0.10:
            score -= 3
        elif candle_delta > 0:
            score += 1
        elif candle_delta < 0:
            score -= 1

        # Preserve original score bounds.
        score = max(-10, min(10, score))

        direction = "BUY" if score >= 0 else "SELL"

        recent_movement = abs(latest - third_last)

        return direction, score, recent_movement

    def reset(self):
        """Reset tick and candle tracking."""
        self.prices.clear()
        self.candle_open = None
        self.candle_minute = None


def momentum_signal(closes, min_samples=8, min_move=0.0):
    """
    Original basic momentum helper.

    Returns BUY, SELL, or None.
    """

    if len(closes) < min_samples:
        return None

    delta = float(closes[-1]) - float(closes[0])

    if abs(delta) <= float(min_move):
        return None

    return "BUY" if delta > 0 else "SELL"


def confirm_signal(primary, confirmations):
    """
    Preserve the existing helper interface.

    This helper is only used when the original engine explicitly
    calls it. It is not automatically added as a new entry filter.
    """

    if primary not in {"BUY", "SELL"}:
        return None

    return primary if all(
        signal == primary for signal in confirmations
    ) else None
