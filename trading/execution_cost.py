
"""
Gold Scalper AI — Adaptive Execution Cost Assessment

Purpose:
- Estimate total trading cost.
- Compare cost with expected opportunity.
- Avoid entries where costs consume too much of the opportunity.
- Avoid fixed spread-pip ceilings.

All monetary inputs must use the same account currency.
For example, if expected_move is USD, spread, commission and slippage
must also be expressed in USD.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ExecutionCostEstimate:
    spread_cost: float
    commission_cost: float
    slippage_cost: float
    total_cost: float
    expected_move: float
    cost_ratio: float
    net_expected_reward: float
    worthwhile: bool


def _valid_nonnegative(value: float, name: str) -> float:
    value = float(value)

    if not isfinite(value):
        raise ValueError(f"{name}_must_be_finite")

    if value < 0:
        raise ValueError(f"{name}_cannot_be_negative")

    return value


def cost_ratio(
    spread: float,
    commission: float,
    expected_move: float,
    slippage: float = 0.0,
) -> float:
    """
    Calculate total execution cost relative to expected favorable movement.

    Returns:
        0.0 when costs are zero and expected move is positive.
        A finite ratio when expected move is positive.
        Infinity when expected move is zero or negative.

    Example:
        Costs = $0.30
        Expected move = $1.00
        Ratio = 0.30, meaning costs consume 30% of expected movement.
    """
    spread = _valid_nonnegative(spread, "spread")
    commission = _valid_nonnegative(commission, "commission")
    slippage = _valid_nonnegative(slippage, "slippage")

    expected_move = float(expected_move)

    if not isfinite(expected_move):
        raise ValueError("expected_move_must_be_finite")

    if expected_move <= 0:
        return float("inf")

    total_cost = spread + commission + slippage

    return total_cost / expected_move


def estimate_execution_cost(
    spread_cost: float,
    commission_cost: float,
    expected_move: float,
    slippage_cost: float = 0.0,
    maximum_cost_ratio: float = 0.30,
) -> ExecutionCostEstimate:
    """
    Produce a complete cost assessment for a potential entry.

    maximum_cost_ratio is a configurable account/product policy.
    It is not a spread-pips restriction.

    The caller should provide a realistic expected_move estimate from
    market intelligence and should not treat it as guaranteed profit.
    """
    spread_cost = _valid_nonnegative(
        spread_cost,
        "spread_cost",
    )

    commission_cost = _valid_nonnegative(
        commission_cost,
        "commission_cost",
    )

    slippage_cost = _valid_nonnegative(
        slippage_cost,
        "slippage_cost",
    )

    expected_move = float(expected_move)

    if not isfinite(expected_move):
        raise ValueError("expected_move_must_be_finite")

    maximum_cost_ratio = float(maximum_cost_ratio)

    if (
        not isfinite(maximum_cost_ratio)
        or maximum_cost_ratio <= 0
        or maximum_cost_ratio > 1
    ):
        raise ValueError("maximum_cost_ratio_must_be_between_0_and_1")

    total_cost = (
        spread_cost
        + commission_cost
        + slippage_cost
    )

    ratio = cost_ratio(
        spread=spread_cost,
        commission=commission_cost,
        slippage=slippage_cost,
        expected_move=expected_move,
    )

    net_expected_reward = expected_move - total_cost

    worthwhile = (
        expected_move > 0
        and ratio <= maximum_cost_ratio
        and net_expected_reward > 0
    )

    return ExecutionCostEstimate(
        spread_cost=spread_cost,
        commission_cost=commission_cost,
        slippage_cost=slippage_cost,
        total_cost=total_cost,
        expected_move=expected_move,
        cost_ratio=ratio,
        net_expected_reward=net_expected_reward,
        worthwhile=worthwhile,
    )


def assess_entry_cost(
    spread_cost: float,
    commission_cost: float,
    expected_move: float,
    slippage_cost: float = 0.0,
    maximum_cost_ratio: float = 0.30,
) -> bool:
    """
    Simple compatibility helper for entry filters.

    Returns True only when the expected opportunity reasonably covers
    the estimated execution costs.
    """
    assessment = estimate_execution_cost(
        spread_cost=spread_cost,
        commission_cost=commission_cost,
        slippage_cost=slippage_cost,
        expected_move=expected_move,
        maximum_cost_ratio=maximum_cost_ratio,
    )

    return assessment.worthwhile
