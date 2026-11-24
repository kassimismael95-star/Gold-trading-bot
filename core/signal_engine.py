from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class MarketTick:
    price: float
    timestamp: datetime


@dataclass
class SignalResult:
    direction: str
    confidence: int
    recent_movement: float


class MicroMomentumTracker:
    """
    Exact original Gold Scalper momentum logic.

    Preserves:
    - 20-tick rolling window
    - Short-term 3-tick movement
    - Full-window movement
    - Current one-minute candle-open movement
    - Confidence range from -10 to +10
    - BUY when confidence is 0 or higher
    - SELL when confidence is below 0
    """

    def __init__(self, capacity: int = 20):
        self.ticks: deque[float] = deque(maxlen=capacity)
        self.candle_open: float | None = None
        self.last_minute: int | None = None

    def record_tick(self, price: float) -> None:
        if price is None or price <= 0:
            return

        current_minute = datetime.now(timezone.utc).minute

        if self.last_minute != current_minute or self.candle_open is None:
            self.candle_open = price
            self.last_minute = current_minute

        self.ticks.append(float(price))

    def evaluate(self) -> SignalResult:
        if len(self.ticks) < 3:
            return SignalResult(
                direction="BUY",
                confidence=6,
                recent_movement=0.0,
            )

        latest = self.ticks[-1]
        score = 0

        short_delta = latest - self.ticks[-3]

        if short_delta > 0.05:
            score += 4
        elif short_delta < -0.05:
            score -= 4
        elif short_delta > 0:
            score += 2
        elif short_delta < 0:
            score -= 2

        full_delta = latest - self.ticks[0]

        if full_delta > 0.15:
            score += 3
        elif full_delta < -0.15:
            score -= 3
        elif full_delta > 0:
            score += 1
        elif full_delta < 0:
            score -= 1

        if self.candle_open is not None:
            candle_delta = latest - self.candle_open

            if candle_delta > 0.10:
                score += 3
            elif candle_delta < -0.10:
                score -= 3
            elif candle_delta > 0:
                score += 1
            elif candle_delta < 0:
                score -= 1

        score = max(-10, min(10, score))

        direction = "BUY" if score >= 0 else "SELL"

        return SignalResult(
            direction=direction,
            confidence=score,
            recent_movement=self.recent_movement(),
        )

    def recent_movement(self) -> float:
        if len(self.ticks) < 3:
            return 0.0

        return abs(self.ticks[-1] - self.ticks[-3])
