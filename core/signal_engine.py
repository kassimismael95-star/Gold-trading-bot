from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class MarketSnapshot:
    bid: float
    ask: float
    tick_count: int
    last_tick_at: datetime | None
    candle_direction: str


@dataclass
class SignalResult:
    signal: str
    reason: str


class SignalEngine:
    TICK_WINDOW = 30
    MAX_TICK_AGE_SECONDS = 10

    def evaluate(self, snapshot: MarketSnapshot) -> SignalResult:
        if snapshot is None:
            return SignalResult(signal="HOLD", reason="No market snapshot available.")

        if snapshot.bid <= 0 or snapshot.ask <= 0:
            return SignalResult(signal="HOLD", reason="Invalid market prices.")

        if snapshot.ask <= snapshot.bid:
            return SignalResult(signal="HOLD", reason="Invalid bid/ask relationship.")

        if snapshot.tick_count <= 0:
            return SignalResult(signal="HOLD", reason="No recent market ticks.")

        if snapshot.last_tick_at is None:
            return SignalResult(signal="HOLD", reason="Market tick time is missing.")

        age_seconds = (datetime.now(timezone.utc) - snapshot.last_tick_at).total_seconds()

        if age_seconds > self.MAX_TICK_AGE_SECONDS:
            return SignalResult(
                signal="HOLD",
                reason=f"Market data is stale by {age_seconds:.1f} seconds.",
            )

        if snapshot.tick_count < self.TICK_WINDOW:
            return SignalResult(
                signal="HOLD",
                reason=f"Waiting for {self.TICK_WINDOW - snapshot.tick_count} more ticks.",
            )

        if snapshot.candle_direction == "up":
            return SignalResult(signal="BUY", reason="One-minute candle direction is up.")

        if snapshot.candle_direction == "down":
            return SignalResult(signal="SELL", reason="One-minute candle direction is down.")

        return SignalResult(signal="HOLD", reason="Candle direction is uncertain.")
