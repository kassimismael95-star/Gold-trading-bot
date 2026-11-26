
"""
Gold Scalper AI
Adaptive execution-cost calculations.

Measures spread, commission, and estimated slippage against
the expected price movement.

This module does not impose a fixed spread ceiling or decide
the trading strategy.
"""

from dataclasses import dataclass
import math


def _valid_number(value):
    """Return a finite float, or None when invalid."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if not math.isfinite(number):
        return None

    return number


def cost_ratio(
    spread,
    commission_equivalent,
    expected_move,
    slippage=0.0,
):
    """
    Calculate total estimated execution cost as a fraction
    of the expected price movement.

    All inputs must use the same price-distance units.

    Returns:
        A ratio such as 0.10 for estimated costs equal to
        10% of the expected movement.

        Returns infinity when expected movement is not positive
        or an input is invalid.
    """

    spread_value = _valid_number(spread)
    commission_value = _valid_number(commission_equivalent)
    expected_value = _valid_number(expected_move)
    slippage_value = _valid_number(slippage)

    if (
        spread_value is None
        or commission_value is None
        or expected_value is None
        or slippage_value is None
    ):
        return float("inf")

    if expected_value <= 0:
        return float("inf")

    total_cost = (
        max(0.0, spread_value)
        + max(0.0, commission_value)
        + max(0.0, slippage_value)
    )

    return total_cost / expected_value


@dataclass(frozen=True)
class ExecutionCostAssessment:
    spread: float
    commission: float
    slippage: float
    expected_move: float
    total_cost: float
    cost_ratio: float
    expected_net_move: float


def assess_execution_cost(
    spread,
    commission_equivalent,
    expected_move,
    slippage=0.0,
):
    """
    Return an execution-cost assessment for the current
    opportunity.

    The assessment is informational. The strategy/risk engine
    decides whether the opportunity is worth taking using
    the user's intended entry logic.
    """

    spread_value = _valid_number(spread)
    commission_value = _valid_number(commission_equivalent)
    expected_value = _valid_number(expected_move)
    slippage_value = _valid_number(slippage)

    if (
        spread_value is None
        or commission_value is None
        or expected_value is None
        or slippage_value is None
    ):
        return ExecutionCostAssessment(
            spread=float("inf"),
            commission=float("inf"),
            slippage=float("inf"),
            expected_move=0.0,
            total_cost=float("inf"),
            cost_ratio=float("inf"),
            expected_net_move=float("-inf"),
        )

    spread_value = max(0.0, spread_value)
    commission_value = max(0.0, commission_value)
    slippage_value = max(0.0, slippage_value)
    expected_value = max(0.0, expected_value)

    total_cost = (
        spread_value
        + commission_value
        + slippage_value
    )

    ratio = (
        total_cost / expected_value
        if expected_value > 0
        else float("inf")
    )

    expected_net_move = expected_value - total_cost

    return ExecutionCostAssessment(
        spread=spread_value,
        commission=commission_value,
        slippage=slippage_value,
        expected_move=expected_value,
        total_cost=total_cost,
        cost_ratio=ratio,
        expected_net_move=expected_net_move,
    )


def acceptable_cost(
    spread,
    commission_equivalent,
    expected_move,
    max_ratio,
    slippage=0.0,
):
    """
    Optional cost-ratio comparison.

    max_ratio must be supplied by the calling trading policy.
    This function does not invent a default acceptance limit.
    """

    ratio_limit = _valid_number(max_ratio)

    if ratio_limit is None or ratio_limit < 0:
        return False

    ratio = cost_ratio(
        spread=spread,
        commission_equivalent=commission_equivalent,
        expected_move=expected_move,
        slippage=slippage,
    )

    return ratio <= ratio_limit
