
from collections import deque
from statistics import median


class ExecutionCostMonitor:
    """
    Observes changing execution costs.

    Measures spread, commission and slippage against expected
    market movement. Maintains a rolling spread baseline.

    This monitor does not close positions, modify SL/TP,
    or impose an arbitrary fixed spread limit.
    """

    def __init__(self, history_size=100):
        self.spread_history = deque(maxlen=history_size)
        self.last_assessment = None

    @staticmethod
    def _number(value):
        value = float(value)

        if value < 0:
            raise ValueError("Execution cost cannot be negative")

        return value

    def assess(
        self,
        spread,
        commission_equivalent=0.0,
        slippage=0.0,
        expected_move=0.0
    ):
        spread = self._number(spread)
        commission = self._number(commission_equivalent)
        slippage = self._number(slippage)
        expected_move = self._number(expected_move)

        self.spread_history.append(spread)

        total_cost = spread + commission + slippage

        historical_baseline = (
            median(self.spread_history)
            if self.spread_history else spread
        )

        spread_vs_baseline = (
            spread / historical_baseline
            if historical_baseline > 0 else None
        )

        cost_ratio = (
            total_cost / expected_move
            if expected_move > 0 else None
        )

        assessment = {
            "spread": spread,
            "commission_equivalent": commission,
            "slippage": slippage,
            "total_execution_cost": total_cost,
            "expected_move": expected_move,
            "cost_to_expected_move_ratio": cost_ratio,
            "historical_median_spread": historical_baseline,
            "spread_vs_historical_baseline": spread_vs_baseline,
            "history_samples": len(self.spread_history),
            "assessment_available": expected_move > 0
        }

        self.last_assessment = assessment
        return assessment


def cost_ratio(spread, commission_equivalent, expected_move):
    """
    Calculate execution cost relative to expected price movement.
    Returns None when expected movement is unavailable.
    """
    spread = float(spread)
    commission = float(commission_equivalent)
    expected_move = float(expected_move)

    if expected_move <= 0:
        return None

    total_cost = max(0.0, spread) + max(0.0, commission)

    return total_cost / expected_move


def acceptable_cost(
    spread,
    commission_equivalent,
    expected_move,
    max_ratio=None
):
    """
    Optional compatibility helper.

    No default cost threshold is imposed.
    A decision is returned only when the caller explicitly
    supplies its own max_ratio.
    """
    if max_ratio is None:
        return None

    ratio = cost_ratio(
        spread,
        commission_equivalent,
        expected_move
    )

    if ratio is None:
        return None

    return ratio <= float(max_ratio)
