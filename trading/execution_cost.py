
"""
Gold Scalper AI — Adaptive Execution Cost Assessment

Compatible with the repository's existing risk engine:
    cost_ratio(spread, commission_equivalent, expected_move)
    acceptable_cost(spread, commission_equivalent, expected_move, max_ratio)

Also supports adaptive intelligence:
    slippage estimates
    detailed cost assessment
    opportunity-relative cost evaluation

All monetary inputs must use the same account currency.
No fixed spread-pips ceiling is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ExecutionCostAssessment:
    spread_cost: float
    commission_cost: float
    slippage_cost: float
    total_cost: float
    expected_move: float
    cost_ratio: float
    net_expected_reward: float
    acceptable: bool


def _nonnegative(value: float, name: str) -> float:
    value = float(value)

    if not isfinite(value):
        raise ValueError(f"{name}_must_be_finite")

    if value < 0:
        raise ValueError(f"{name}_cannot_be_negative")

    return value


def cost_ratio(
    spread,
    commission_equivalent,
    expected_move,
    slippage=0.0,
):
    """
    Calculate estimated execution cost / expected favorable movement.

    Returns infinity when expected_move is zero or negative.

    Existing three-argument calls remain valid.
    """
    spread = _nonnegative(spread, "spread")
    commission_equivalent = _nonnegative(
        commission_equivalent,
        "commission_equivalent",
    )
    slippage = _nonnegative(slippage, "slippage")

    expected_move = float(expected_move)

    if not isfinite(expected_move):
        raise ValueError("expected_move_must_be_finite")

    if expected_move <= 0:
        return float("inf")

    total_cost = (
        spread
        + commission_equivalent
        + slippage
    )

    return total_cost / expected_move


def acceptable_cost(
    spread,
    commission_equivalent,
    expected_move,
    max_ratio=0.30,
    slippage=0.0,
):
    """
    Compatibility function used by the existing risk engine.

    The ratio is relative to expected opportunity, not a fixed pip limit.
    """
    max_ratio = float(max_ratio)

    if (
        not isfinite(max_ratio)
        or max_ratio <= 0
        or max_ratio > 1
    ):
        raise ValueError("max_ratio_must_be_between_0_and_1")

    ratio = cost_ratio(
        spread=spread,
        commission_equivalent=commission_equivalent,
        expected_move=expected_move,
        slippage=slippage,
    )

    return ratio <= max_ratio


def assess_execution_cost(
    spread_cost,
    commission_cost,
    expected_move,
    slippage_cost=0.0,
    max_cost_ratio=0.30,
):
    """
    Return a detailed execution-cost assessment for market intelligence.

    The caller must estimate expected_move conservatively.
    It is an estimate, not a guaranteed profit.
    """
    spread_cost = _nonnegative(
        spread_cost,
        "spread_cost",
    )

    commission_cost = _nonnegative(
        commission_cost,
        "commission_cost",
    )

    slippage_cost = _nonnegative(
        slippage_cost,
        "slippage_cost",
    )

    expected_move = float(expected_move)

    if not isfinite(expected_move):
        raise ValueError("expected_move_must_be_finite")

    max_cost_ratio = float(max_cost_ratio)

    if (
        not isfinite(max_cost_ratio)
        or max_cost_ratio <= 0
        or max_cost_ratio > 1
    ):
        raise ValueError("max_cost_ratio_must_be_between_0_and_1")

    total_cost = (
        spread_cost
        + commission_cost
        + slippage_cost
    )

    ratio = cost_ratio(
        spread=spread_cost,
        commission_equivalent=commission_cost,
        expected_move=expected_move,
        slippage=slippage_cost,
    )

    net_expected_reward = expected_move - total_cost

    acceptable = (
        expected_move > 0
        and ratio <= max_cost_ratio
        and net_expected_reward > 0
    )

    return ExecutionCostAssessment(
        spread_cost=spread_cost,
        commission_cost=commission_cost,
        slippage_cost=slippage_cost,
        total_cost=total_cost,
        expected_move=expected_move,
        cost_ratio=ratio,
        net_expected_reward=net_expected_reward,
        acceptable=acceptable,
    )
