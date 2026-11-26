
from collections import deque
from datetime import datetime, timezone


class MicroMomentumTracker:
    """
    Original Gold Scalper AI micro-momentum tracker.

    This tracker preserves the original entry-engine interface:
        tracker = MicroMomentumTracker(capacity=20)
        tracker.record_tick(price)
        movement = tracker.recent_movement()
        direction, confidence = tracker.evaluate()

    It does not independently open trades or impose entry filters.
    """

    def __init__(self, capacity=20):
        if capacity < 3:
            raise ValueError("capacity must be at least 3")

        self.ticks = deque(maxlen=capacity)
        self.candle_open = None
        self.last_minute = None

    def record_tick(self, price):
        """
        Record the latest market price.

        A new candle reference is established when the UTC minute changes.
        """
        price = float(price)

        current_minute = datetime.now(timezone.utc).replace(
            second=0,
            microsecond=0
        )

        if (
            self.last_minute != current_minute
            or self.candle_open is None
        ):
            self.candle_open = price
            self.last_minute = current_minute

        self.ticks.append(price)

    def evaluate(self):
        """
        Original momentum scoring.

        Returns:
            (direction, confidence_score)
        """
        if len(self.ticks) < 3:
            return "BUY", 6

        score = 0

        latest = self.ticks[-1]

        # Short-term momentum
        short_delta = latest - self.ticks[-3]

        if short_delta > 0.05:
            score += 4
        elif short_delta < -0.05:
            score -= 4
        elif short_delta > 0:
            score += 2
        elif short_delta < 0:
            score -= 2

        # Overall movement across recorded ticks
        full_delta = latest - self.ticks[0]

        if full_delta > 0.15:
            score += 3
        elif full_delta < -0.15:
            score -= 3
        elif full_delta > 0:
            score += 1
        elif full_delta < 0:
            score -= 1

        # Movement relative to the current UTC minute's opening price
        candle_delta = latest - self.candle_open

        if candle_delta > 0.10:
            score += 3
        elif candle_delta < -0.10:
            score -= 3
        elif candle_delta > 0:
            score += 1
        elif candle_delta < 0:
            score -= 1

        # Preserve the original score range
        score = max(-10, min(10, score))

        direction = "BUY" if score >= 0 else "SELL"

        return direction, score

    def recent_movement(self):
        """
        Original recent-movement calculation.
        """
        if len(self.ticks) < 3:
            return 0.0

        return abs(self.ticks[-1] - self.ticks[-3])
