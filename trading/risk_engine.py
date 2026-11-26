
"""
Adaptive risk and position intelligence for Gold Scalper AI.

The RiskEngine evaluates entries and manages position protection.
It does not use an independent fixed drawdown breaker.

The intelligence layer remains responsible for trading decisions.
Broker execution constraints can still reject an order or modification.

Each account should have its own RiskEngine instance.

Existing RiskEngine.allow_entry(...) interface is preserved.
Protective stops are never moved in a greater-risk direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import inf, isfinite
from typing import Optional


class PositionAction(str, Enum):
    HOLD = "HOLD"
    MODIFY_PROTECTION = "MODIFY_PROTECTION"
    CLOSE = "CLOSE"


@dataclass(frozen=True)
class MarketState:
    momentum: float
    reversal_strength: float
    continuation_strength: float
    expected_move_usd: float
    execution_cost_usd: float
    volatility_usd: float

    def __post_init__(self) -> None:
        values = (
            self.momentum,
            self.reversal_strength,
            self.continuation_strength,
            self.expected_move_usd,
            self.execution_cost_usd,
            self.volatility_usd,
        )

        if not all(isfinite(float(value)) for value in values):
            raise ValueError("MarketState values must be finite.")

        if not -10.0 <= self.momentum <= 10.0:
            raise ValueError("momentum must be between -10 and 10.")

        if not 0.0 <= self.reversal_strength <= 1.0:
            raise ValueError("reversal_strength must be between 0 and 1.")

        if not 0.0 <= self.continuation_strength <= 1.0:
            raise ValueError("continuation_strength must be between 0 and 1.")

        if self.expected_move_usd < 0.0:
            raise ValueError("expected_move_usd cannot be negative.")

        if self.execution_cost_usd < 0.0:
            raise ValueError("execution_cost_usd cannot be negative.")

        if self.volatility_usd < 0.0:
            raise ValueError("volatility_usd cannot be negative.")


@dataclass(frozen=True)
class PositionState:
    position_id: int
    direction: str
    volume: float
    entry_price: float
    current_price: float
    profit_usd: float
    peak_profit_usd: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    usd_per_price_unit_per_lot: float

    def __post_init__(self) -> None:
        direction = str(self.direction).upper()

        if direction not in ("BUY", "SELL"):
            raise ValueError("direction must be BUY or SELL.")

        numeric_values = (
            self.volume,
            self.entry_price,
            self.current_price,
            self.profit_usd,
            self.peak_profit_usd,
            self.usd_per_price_unit_per_lot,
        )

        if not all(isfinite(float(value)) for value in numeric_values):
            raise ValueError("PositionState values must be finite.")

        if self.stop_loss is not None and not isfinite(float(self.stop_loss)):
            raise ValueError("stop_loss must be finite or None.")

        if self.take_profit is not None and not isfinite(float(self.take_profit)):
            raise ValueError("take_profit must be finite or None.")

        if self.volume <= 0.0:
            raise ValueError("volume must be greater than zero.")

        if self.entry_price <= 0.0 or self.current_price <= 0.0:
            raise ValueError("Prices must be greater than zero.")

        if self.usd_per_price_unit_per_lot <= 0.0:
            raise ValueError(
                "usd_per_price_unit_per_lot must be greater than zero."
            )


@dataclass(frozen=True)
class PositionDecision:
    action: PositionAction
    reason: str
    desired_stop_loss: Optional[float]
    desired_take_profit: Optional[float]
    lock_profit_usd: float
    estimated_remaining_reward_usd: float


class RiskEngine:
    """
    Adaptive entry and position-management engine.

    drawdown_limit is retained for compatibility with existing callers.
    It is intentionally not used as an independent trading breaker.
    """

    def __init__(
        self,
        drawdown_limit: float = 35.0,
        max_positions: int = 18,
        max_cost_ratio: float = 0.30,
        base_stop_loss_usd: float = 2.00,
        base_take_profit_usd: float = 2.20,
        min_stop_loss_usd: float = 1.50,
        max_stop_loss_usd: float = 3.00,
        min_take_profit_usd: float = 1.80,
        max_take_profit_usd: float = 3.50,
        reversal_close_strength: float = 0.85,
        profit_lock_start_usd: float = 0.50,
        profit_lock_fraction: float = 0.60,
        minimum_reward_cost_ratio: float = 1.0,
    ) -> None:
        self.drawdown_limit = float(drawdown_limit)
        self.max_positions = int(max_positions)
        self.max_cost_ratio = float(max_cost_ratio)

        self.base_stop_loss_usd = float(base_stop_loss_usd)
        self.base_take_profit_usd = float(base_take_profit_usd)

        self.min_stop_loss_usd = float(min_stop_loss_usd)
        self.max_stop_loss_usd = float(max_stop_loss_usd)

        self.min_take_profit_usd = float(min_take_profit_usd)
        self.max_take_profit_usd = float(max_take_profit_usd)

        self.reversal_close_strength = float(reversal_close_strength)
        self.profit_lock_start_usd = float(profit_lock_start_usd)
        self.profit_lock_fraction = float(profit_lock_fraction)
        self.minimum_reward_cost_ratio = float(minimum_reward_cost_ratio)

        self._validate_configuration()

    def _validate_configuration(self) -> None:
        numeric_settings = (
            self.drawdown_limit,
            self.max_cost_ratio,
            self.base_stop_loss_usd,
            self.base_take_profit_usd,
            self.min_stop_loss_usd,
            self.max_stop_loss_usd,
            self.min_take_profit_usd,
            self.max_take_profit_usd,
            self.reversal_close_strength,
            self.profit_lock_start_usd,
            self.profit_lock_fraction,
            self.minimum_reward_cost_ratio,
        )

        if not all(isfinite(value) for value in numeric_settings):
            raise ValueError("RiskEngine configuration must be finite.")

        if self.max_positions < 1:
            raise ValueError("max_positions must be at least 1.")

        if self.max_cost_ratio < 0.0:
            raise ValueError("max_cost_ratio cannot be negative.")

        if self.min_stop_loss_usd <= 0.0:
            raise ValueError("min_stop_loss_usd must be positive.")

        if self.max_stop_loss_usd < self.min_stop_loss_usd:
            raise ValueError("Invalid stop-loss range.")

        if self.min_take_profit_usd <= 0.0:
            raise ValueError("min_take_profit_usd must be positive.")

        if self.max_take_profit_usd < self.min_take_profit_usd:
            raise ValueError("Invalid take-profit range.")

        if not 0.0 <= self.reversal_close_strength <= 1.0:
            raise ValueError(
                "reversal_close_strength must be between 0 and 1."
            )

        if self.profit_lock_start_usd < 0.0:
            raise ValueError("profit_lock_start_usd cannot be negative.")

        if not 0.0 <= self.profit_lock_fraction <= 1.0:
            raise ValueError(
                "profit_lock_fraction must be between 0 and 1."
            )

        if self.minimum_reward_cost_ratio < 0.0:
            raise ValueError(
                "minimum_reward_cost_ratio cannot be negative."
            )

    @staticmethod
    def _cost_ratio(
        spread: float,
        commission: float,
        expected_move: float,
    ) -> float:
        """
        Return estimated execution cost divided by expected movement.

        Costs are treated as non-negative monetary values.
        """
        if expected_move <= 0.0:
            return inf

        total_cost = max(0.0, float(spread)) + max(
            0.0, float(commission)
        )

        return total_cost / float(expected_move)

    def allow_entry(
        self,
        initial_equity: float,
        equity: float,
        open_count: int,
        free_margin: float,
        required_margin: float,
        spread: float,
        commission: float,
        expected_move: float,
    ) -> bool:
        """
        Evaluate whether a new entry is acceptable.

        initial_equity and equity are retained in the interface for
        compatibility and intelligence-layer drawdown analysis.

        This method does not independently trigger a 35% drawdown
        breaker or force-close positions.
        """
        values = (
            initial_equity,
            equity,
            free_margin,
            required_margin,
            spread,
            commission,
            expected_move,
        )

        if not all(isfinite(float(value)) for value in values):
            return False

        if int(open_count) < 0:
            return False

        if expected_move <= 0.0:
            return False

        if required_margin < 0.0 or free_margin < 0.0:
            return False

        # Internal entry capacity check.
        if int(open_count) >= self.max_positions:
            return False

        # Required margin must be available before sending the order.
        if required_margin > free_margin:
            return False

        # Adaptive cost check: no fixed spread-in-pips ceiling.
        ratio = self._cost_ratio(
            spread=spread,
            commission=commission,
            expected_move=expected_move,
        )

        if ratio > self.max_cost_ratio:
            return False

        return True

    @staticmethod
    def _money_to_price_distance(
        money: float,
        volume: float,
        contract_value: float,
    ) -> float:
        denominator = volume * contract_value

        if denominator <= 0.0:
            raise ValueError("Invalid volume or contract value.")

        return max(0.0, money) / denominator

    @staticmethod
    def _directional_price(
        entry_price: float,
        direction: str,
        distance: float,
    ) -> float:
        direction = direction.upper()

        if direction == "BUY":
            return entry_price + distance

        if direction == "SELL":
            return entry_price - distance

        raise ValueError("direction must be BUY or SELL.")

    @staticmethod
    def _stop_is_more_protective(
        direction: str,
        candidate: float,
        current: Optional[float],
    ) -> bool:
        if current is None:
            return True

        if direction == "BUY":
            return candidate > current

        return candidate < current

    @staticmethod
    def _tp_is_farther_in_profit(
        direction: str,
        candidate: float,
        current: Optional[float],
    ) -> bool:
        if current is None:
            return True

        if direction == "BUY":
            return candidate > current

        return candidate < current

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    def manage_position(
        self,
        position: PositionState,
        market: MarketState,
    ) -> PositionDecision:
        """
        Evaluate a position and return an intelligence decision.

        The caller is responsible for submitting the returned action
        to the broker and checking whether the broker accepted it.
        """
        direction = position.direction.upper()

        signed_momentum = (
            market.momentum
            if direction == "BUY"
            else -market.momentum
        )

        momentum_alignment = self._clamp(
            signed_momentum / 10.0,
            0.0,
            1.0,
        )

        continuation_score = (
            market.continuation_strength * momentum_alignment
        )

        reversal_against_position = market.reversal_strength

        reward_cost_ratio = (
            market.expected_move_usd / market.execution_cost_usd
            if market.execution_cost_usd > 0.0
            else inf
        )

        # Close only when the intelligence detects a strong opposing
        # reversal and the position currently has positive profit.
        if (
            reversal_against_position
            >= self.reversal_close_strength
            and position.profit_usd > 0.0
        ):
            return PositionDecision(
                action=PositionAction.CLOSE,
                reason="Strong opposing reversal while position is profitable.",
                desired_stop_loss=position.stop_loss,
                desired_take_profit=position.take_profit,
                lock_profit_usd=position.profit_usd,
                estimated_remaining_reward_usd=0.0,
            )

        stop_money = self._clamp(
            self.base_stop_loss_usd,
            self.min_stop_loss_usd,
            self.max_stop_loss_usd,
        )

        target_money = self._clamp(
            self.base_take_profit_usd,
            self.min_take_profit_usd,
            self.max_take_profit_usd,
        )

        weakness = max(
            1.0 - continuation_score,
            reversal_against_position,
        )

        if weakness >= 0.70:
            stop_money *= 0.65
        elif weakness >= 0.50:
            stop_money *= 0.80

        stop_money = self._clamp(
            stop_money,
            self.min_stop_loss_usd,
            self.max_stop_loss_usd,
        )

        # Extend the target only when continuation is strong and the
        # expected movement justifies the execution cost.
        if (
            continuation_score >= 0.70
            and reward_cost_ratio >= self.minimum_reward_cost_ratio
            and market.expected_move_usd > target_money
        ):
            extension_factor = 1.0 + (
                continuation_score - 0.70
            ) * 2.0

            target_money *= extension_factor

        target_money = self._clamp(
            target_money,
            self.min_take_profit_usd,
            self.max_take_profit_usd,
        )

        stop_distance = self._money_to_price_distance(
            money=stop_money,
            volume=position.volume,
            contract_value=position.usd_per_price_unit_per_lot,
        )

        target_distance = self._money_to_price_distance(
            money=target_money,
            volume=position.volume,
            contract_value=position.usd_per_price_unit_per_lot,
        )

        # Correct stop-loss direction:
        # BUY stop is below entry; SELL stop is above entry.
        # Negative distance works correctly for both directions.
        candidate_sl = self._directional_price(
            position.entry_price,
            direction,
            -stop_distance,
        )

        candidate_tp = self._directional_price(
            position.entry_price,
            direction,
            target_distance,
        )

        lock_profit_usd = 0.0

        if position.profit_usd >= self.profit_lock_start_usd:
            lock_profit_usd = max(
                position.profit_usd,
                position.peak_profit_usd,
            ) * self.profit_lock_fraction

            lock_distance = self._money_to_price_distance(
                money=lock_profit_usd,
                volume=position.volume,
                contract_value=position.usd_per_price_unit_per_lot,
            )

            lock_sl = self._directional_price(
                position.entry_price,
                direction,
                lock_distance,
            )

            if self._stop_is_more_protective(
                direction,
                lock_sl,
                candidate_sl,
            ):
                candidate_sl = lock_sl

        # Never move an existing protective stop in the greater-risk
        # direction. Keep the more protective of the two values.
        if position.stop_loss is not None:
            if self._stop_is_more_protective(
                direction,
                position.stop_loss,
                candidate_sl,
            ):
                candidate_sl = position.stop_loss

        # Never move an existing TP closer to the entry.
        if position.take_profit is not None:
            if self._tp_is_farther_in_profit(
                direction,
                position.take_profit,
                candidate_tp,
            ):
                candidate_tp = position.take_profit

        sl_changed = (
            position.stop_loss is None
            or abs(candidate_sl - position.stop_loss) > 1e-9
        )

        tp_changed = (
            position.take_profit is None
            or abs(candidate_tp - position.take_profit) > 1e-9
        )

        if sl_changed or tp_changed:
            action = PositionAction.MODIFY_PROTECTION
            reason = (
                "Adaptive protection updated from momentum, "
                "continuation, reversal, and profit-lock analysis."
            )
        else:
            action = PositionAction.HOLD
            reason = "Current protection remains appropriate."

        return PositionDecision(
            action=action,
            reason=reason,
            desired_stop_loss=candidate_sl,
            desired_take_profit=candidate_tp,
            lock_profit_usd=lock_profit_usd,
            estimated_remaining_reward_usd=target_money,
        )
