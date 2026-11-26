
"""
Gold Scalper AI — Adaptive Market Intelligence

Preserves the original micro-momentum strategy:
- Rolling tick history
- Short-term price delta
- Full-window price delta
- Current-candle movement
- Signed momentum score from -10 to +10

Adds adaptive intelligence:
- Directional continuation strength
- Reversal strength against the current position
- Momentum weakening detection
- Short-term volatility estimate
- Recent movement estimate

This module is intentionally broker-independent.
It does not open or close orders.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from statistics import mean, pstdev
from typing import Deque, Iterable, Optional


@dataclass(frozen=True)
class MarketSnapshot:
    timestamp: datetime
    price: float
    direction: str
    momentum_score: float
    confidence: float
    continuation_strength: float
    reversal_strength: float
    momentum_weakening: bool
    recent_movement: float
    volatility: float
    candle_movement: float
    tick_count: int


class MicroMomentumTracker:
    """
    Original micro-momentum logic, retained and extended.

    Original score components:
        Short-term movement: up to +/-4
        Full-window movement: up to +/-3
        Candle movement: up to +/-3

    Total score is clamped to [-10, +10].
    """

    def __init__(
        self,
        max_ticks: int = 20,
        short_window: int = 3,
        short_move_threshold: float = 0.05,
        full_move_threshold: float = 0.15,
        candle_move_threshold: float = 0.10,
    ):
        if max_ticks < 5:
            raise ValueError("max_ticks_must_be_at_least_5")

        if short_window < 2:
            raise ValueError("short_window_must_be_at_least_2")

        self.max_ticks = int(max_ticks)
        self.short_window = int(short_window)

        self.short_move_threshold = float(short_move_threshold)
        self.full_move_threshold = float(full_move_threshold)
        self.candle_move_threshold = float(candle_move_threshold)

        self.ticks: Deque[tuple[datetime, float]] = deque(
            maxlen=self.max_ticks
        )

        self.candle_open: Optional[float] = None
        self.candle_start: Optional[datetime] = None

        self._previous_score: Optional[float] = None
        self._previous_direction: Optional[str] = None

    @staticmethod
    def _utc_timestamp(timestamp=None) -> datetime:
        if timestamp is None:
            return datetime.now(timezone.utc)

        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)

        return timestamp.astimezone(timezone.utc)

    def reset(self):
        self.ticks.clear()
        self.candle_open = None
        self.candle_start = None
        self._previous_score = None
        self._previous_direction = None

    def record_tick(self, price: float, timestamp=None):
        price = float(price)

        if not isfinite(price) or price <= 0:
            raise ValueError("price_must_be_finite_and_positive")

        now = self._utc_timestamp(timestamp)

        # Candle boundaries are UTC minute boundaries.
        minute_start = now.replace(second=0, microsecond=0)

        if self.candle_start != minute_start:
            self.candle_start = minute_start
            self.candle_open = price

        self.ticks.append((now, price))

    def _prices(self) -> list[float]:
        return [price for _, price in self.ticks]

    def recent_movement(self) -> float:
        prices = self._prices()

        if len(prices) < self.short_window:
            return 0.0

        return abs(prices[-1] - prices[-self.short_window])

    def candle_movement(self) -> float:
        if self.candle_open is None or not self.ticks:
            return 0.0

        return self.ticks[-1][1] - self.candle_open

    def volatility(self) -> float:
        """
        Population standard deviation of recent price changes.

        This is a price-unit volatility estimate, not a pip value.
        """
        prices = self._prices()

        if len(prices) < 3:
            return 0.0

        changes = [
            prices[index] - prices[index - 1]
            for index in range(1, len(prices))
        ]

        return pstdev(changes) if len(changes) > 1 else abs(changes[0])

    def evaluate_score(self) -> tuple[str, float]:
        prices = self._prices()

        if len(prices) < 3:
            return "BUY", 6.0

        score = 0.0

        # Short-term delta: latest tick versus the third-last tick.
        short_delta = prices[-1] - prices[-3]

        if short_delta > self.short_move_threshold:
            score += 4.0
        elif short_delta < -self.short_move_threshold:
            score -= 4.0
        elif short_delta > 0:
            score += 2.0
        elif short_delta < 0:
            score -= 2.0

        # Full-window delta.
        full_delta = prices[-1] - prices[0]

        if full_delta > self.full_move_threshold:
            score += 3.0
        elif full_delta < -self.full_move_threshold:
            score -= 3.0
        elif full_delta > 0:
            score += 1.0
        elif full_delta < 0:
            score -= 1.0

        # Current candle movement.
        candle_delta = self.candle_movement()

        if candle_delta > self.candle_move_threshold:
            score += 3.0
        elif candle_delta < -self.candle_move_threshold:
            score -= 3.0
        elif candle_delta > 0:
            score += 1.0
        elif candle_delta < 0:
            score -= 1.0

        score = max(-10.0, min(10.0, score))

        direction = "BUY" if score >= 0 else "SELL"

        self._previous_score = score
        self._previous_direction = direction

        return direction, score

    def _directional_consistency(self) -> float:
        prices = self._prices()

        if len(prices) < 4:
            return 0.0

        changes = [
            prices[index] - prices[index - 1]
            for index in range(1, len(prices))
        ]

        positive = sum(change > 0 for change in changes)
        negative = sum(change < 0 for change in changes)
        nonzero = positive + negative

        if nonzero == 0:
            return 0.0

        return max(positive, negative) / nonzero

    def continuation_strength(self, direction: str) -> float:
        """
        Estimate how consistently recent price changes support direction.

        Returns a normalized value from 0.0 to 1.0.
        """
        direction = direction.upper()

        if direction not in {"BUY", "SELL"}:
            return 0.0

        prices = self._prices()

        if len(prices) < 4:
            return 0.0

        changes = [
            prices[index] - prices[index - 1]
            for index in range(1, len(prices))
        ]

        aligned = 0
        nonzero = 0

        for change in changes:
            if change == 0:
                continue

            nonzero += 1

            if direction == "BUY" and change > 0:
                aligned += 1
            elif direction == "SELL" and change < 0:
                aligned += 1

        if nonzero == 0:
            return 0.0

        consistency = aligned / nonzero

        _, score = self.evaluate_score()

        score_alignment = (
            max(0.0, score / 10.0)
            if direction == "BUY"
            else max(0.0, -score / 10.0)
        )

        # Both price consistency and the original momentum score matter.
        return max(
            0.0,
            min(1.0, consistency * 0.60 + score_alignment * 0.40),
        )

    def reversal_strength(self, position_direction: str) -> float:
        """
        Estimate reversal evidence against an existing position.

        BUY position:
            Negative momentum increases reversal strength.

        SELL position:
            Positive momentum increases reversal strength.
        """
        position_direction = position_direction.upper()

        if position_direction not in {"BUY", "SELL"}:
            return 0.0

        _, score = self.evaluate_score()

        if position_direction == "BUY":
            opposing_score = max(0.0, -score / 10.0)
        else:
            opposing_score = max(0.0, score / 10.0)

        prices = self._prices()

        if len(prices) < 4:
            return opposing_score

        recent_delta = prices[-1] - prices[-3]

        recent_opposition = (
            recent_delta < 0
            if position_direction == "BUY"
            else recent_delta > 0
        )

        recent_factor = 1.0 if recent_opposition else 0.5

        return max(
            0.0,
            min(1.0, opposing_score * recent_factor),
        )

    def momentum_weakening(self, direction: str) -> bool:
        """
        Detect whether the latest movement is losing directional strength.

        This is a warning signal, not an automatic close instruction.
        """
        direction = direction.upper()

        if direction not in {"BUY", "SELL"}:
            return True

        prices = self._prices()

        if len(prices) < 5:
            return False

        first_delta = prices[-3] - prices[-5]
        latest_delta = prices[-1] - prices[-3]

        if direction == "BUY":
            return latest_delta <= 0 or abs(latest_delta) < abs(first_delta) * 0.35

        return latest_delta >= 0 or abs(latest_delta) < abs(first_delta) * 0.35

    def snapshot(self) -> MarketSnapshot:
        if not self.ticks:
            raise RuntimeError("no_market_ticks_recorded")

        price = self.ticks[-1][1]
        direction, score = self.evaluate_score()

        continuation = self.continuation_strength(direction)

        # Confidence combines original score magnitude and directional
        # consistency. It is a signal-strength estimate, not a probability.
        consistency = self._directional_consistency()

        confidence = max(
            0.0,
            min(
                10.0,
                abs(score) * 0.70 + consistency * 3.0,
            ),
        )

        return MarketSnapshot(
            timestamp=self.ticks[-1][0],
            price=price,
            direction=direction,
            momentum_score=score,
            confidence=confidence,
            continuation_strength=continuation,
            reversal_strength=0.0,
            momentum_weakening=self.momentum_weakening(direction),
            recent_movement=self.recent_movement(),
            volatility=self.volatility(),
            candle_movement=self.candle_movement(),
            tick_count=len(self.ticks),
        )


class MarketIntelligence:
    """
    Account-independent live market analyzer.

    One instance should be maintained per symbol/market stream.
    Position-specific reversal strength is calculated separately for
    each open position using evaluate_for_position().
    """

    def __init__(self, max_ticks: int = 20):
        self.tracker = MicroMomentumTracker(max_ticks=max_ticks)

    def update(self, price: float, timestamp=None) -> MarketSnapshot:
        self.tracker.record_tick(price, timestamp)
        return self.tracker.snapshot()

    def evaluate_for_position(
        self,
        position_direction: str,
    ) -> MarketSnapshot:
        base = self.tracker.snapshot()

        return MarketSnapshot(
            timestamp=base.timestamp,
            price=base.price,
            direction=base.direction,
            momentum_score=base.momentum_score,
            confidence=base.confidence,
            continuation_strength=self.tracker.continuation_strength(
                position_direction
            ),
            reversal_strength=self.tracker.reversal_strength(
                position_direction
            ),
            momentum_weakening=self.tracker.momentum_weakening(
                position_direction
            ),
            recent_movement=base.recent_movement,
            volatility=base.volatility,
            candle_movement=base.candle_movement,
            tick_count=base.tick_count,
        )

    def reset(self):
        self.tracker.reset()
