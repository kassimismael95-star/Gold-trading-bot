from collections import deque
import datetime


class MicroMomentumTracker:
    def __init__(self, capacity=20):
        self.ticks = deque(maxlen=capacity)
        self.candle_open = None
        self.last_minute = None

    def record_tick(self, price):
        current_minute = datetime.datetime.now(
            datetime.timezone.utc
        ).minute

        if self.last_minute != current_minute or self.candle_open is None:
            self.candle_open = price
            self.last_minute = current_minute

        self.ticks.append(price)

    def evaluate(self):
        if len(self.ticks) < 3:
            return "BUY", 6

        score = 0
        latest = self.ticks[-1]

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

        return direction, score

    def recent_movement(self):
        if len(self.ticks) < 3:
            return 0.0

        return abs(self.ticks[-1] - self.ticks[-3])
