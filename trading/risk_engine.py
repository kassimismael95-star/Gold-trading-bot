
"""
Adaptive risk and position intelligence for Gold Scalper AI.

This module is broker-independent. It produces risk and position-management
decisions; the execution layer must validate broker constraints and apply
SL/TP modifications.

Important:
- No fixed 35-pip spread ceiling.
- Each account should use its own RiskEngine instance and settings.
- Existing RiskEngine.allow_entry(...) interface is preserved.
- Protective stops are never moved in the direction of greater risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Optional

from .drawdown_monitor import breaker_triggered
from .execution_cost import cost_ratio
from .account_limits import can_open_new_position


class PositionAction(str, Enum):
    HOLD = "HOLD"
    MODIFY_PROTECTION = "MODIFY_PROTECTION"
    CLOSE = "CLOSE"


@dataclass(frozen=True)
class MarketState:
    """
    Normalized market intelligence supplied by the market-analysis layer.

    momentum:
        Signed score from -10 to +10.
        Positive = bullish, negative = bearish.

    reversal_strength:
        0.0 to 1.0. Higher values mean stronger evidence of reversal
        against the current position.

    continuation_strength:
        0.0 to 1.0. Higher values mean stronger evidence that the
        current directional move is continuing.

    expected_move_usd:
        Estimated remaining favorable price movement, expressed in
        account-currency profit for the position volume.

    execution_cost_usd:
        Estimated spread + commission + slippage for the position.

    volatility_usd:
        Current market movement estimate expressed in account currency.
    """

    momentum: float
    reversal_strength: float
    continuation_strength: float
    expected_move_usd: float
    execution_cost_usd: float
    volatility_usd: float = 0.0

    def __post_init__(self):
        values = (
            self.momentum,
            self.reversal_strength,
            self.continuation_strength,
            self.expected_move_usd,
            self.execution_cost_usd,
            self.volatility_usd,
        )
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("market_state_values_must_be_finite")

        if not -10.0 <= self.momentum <= 10.0:
            raise ValueError("momentum_must_be_between_minus_10_and_10")

        if not 0.0 <= self.reversal_strength <= 1.0:
            raise ValueError("reversal_strength_must_be_between_0_and_1")

        if not 0.0 <= self.continuation_strength <= 1.0:
            raise ValueError("continuation_strength_must_be_between_0_and_1")

        if self.expected_move_usd < 0:
            raise ValueError("expected_move_usd_cannot_be_negative")

        if self.execution_cost_usd < 0:
            raise ValueError("execution_cost_usd_cannot_be_negative")

        if self.volatility_usd < 0:
            raise ValueError("volatility_usd_cannot_be_negative")


@dataclass(frozen=True)
class PositionState:
    """
    Live position data required for adaptive management.

    usd_per_price_unit_per_lot must come from the broker's symbol
    specification or a broker-calculated contract-value function.

    Example:
        If a 1.00 price-unit move on 1.00 lot is worth $100,
        usd_per_price_unit_per_lot = 100.0.

    Do not assume this value is identical across brokers or symbols.
    """

    position_id: str
    direction: str
    volume: float
    entry_price: float
    current_price: float
    profit_usd: float
    peak_profit_usd: float
    current_sl_price: Optional[float]
    current_tp_price: Optional[float]
    usd_per_price_unit_per_lot: float

    def __post_init__(self):
        if self.direction.upper() not in {"BUY", "SELL"}:
            raise ValueError("direction_must_be_BUY_or_SELL")

        if not self.position_id:
            raise ValueError("position_id_required")

        numeric_values = (
            self.volume,
            self.entry_price,
            self.current_price,
            self.profit_usd,
            self.peak_profit_usd,
            self.usd_per_price_unit_per_lot,
        )

        if not all(isfinite(float(value)) for value in numeric_values):
            raise ValueError("position_values_must_be_finite")

        if self.volume <= 0:
            raise ValueError("volume_must_be_positive")

        if self.usd_per_price_unit_per_lot <= 0:
            raise ValueError("broker_contract_value_must_be_positive")


@dataclass(frozen=True)
class PositionDecision:
    action: PositionAction
    reason: str
    desired_sl_price: Optional[float]
    desired_tp_price: Optional[float]
    lock_profit_usd: float
    estimated_remaining_reward_usd: float


class RiskEngine:
    """
    Account-specific adaptive risk policy.

    Create one instance per trading account. Do not share adaptive state
    between different users or accounts.

    The engine does not send orders itself. It returns decisions for the
    execution layer to validate and apply.
    """

    def __init__(
        self,
        drawdown_limit: float = 35.0,
        max_positions: int = 18,
        max_cost_ratio: float = 0.30,
        base_stop_loss_usd: float = 2.00,
        base_take_profit_usd: float = 2.20,
        minimum_stop_loss_usd: float = 1.50,
        maximum_stop_loss_usd: float = 3.00,
        minimum_take_profit_usd: float = 1.80,
        maximum_take_profit_usd: float = 3.50,
        reversal_close_strength: float = 0.85,
        profit_lock_start_usd: float = 0.50,
        profit_lock_fraction: float = 0.60,
        minimum_reward_cost_ratio: float = 1.0,
    ):
        self.drawdown_limit = float(drawdown_limit)
        self.max_positions = int(max_positions)
        self.max_cost_ratio = float(max_cost_ratio)

        self.base_stop_loss_usd = float(base_stop_loss_usd)
        self.base_take_profit_usd = float(base_take_profit_usd)

        self.minimum_stop_loss_usd = float(minimum_stop_loss_usd)
        self.maximum_stop_loss_usd = float(maximum_stop_loss_usd)

        self.minimum_take_profit_usd = float(minimum_take_profit_usd)
        self.maximum_take_profit_usd = float(maximum_take_profit_usd)

        self.reversal_close_strength = float(reversal_close_strength)
        self.profit_lock_start_usd = float(profit_lock_start_usd)
        self.profit_lock_fraction = float(profit_lock_fraction)
        self.minimum_reward_cost_ratio = float(minimum_reward_cost_ratio)

        self._validate_configuration()

    def _validate_configuration(self):
        if not 0 < self.drawdown_limit <= 100:
            raise ValueError("drawdown_limit_must_be_between_0_and_100")

        if self.max_positions < 1:
            raise ValueError("max_positions_must_be_at_least_1")

        if not 0 < self.max_cost_ratio <= 1:
            raise ValueError("max_cost_ratio_must_be_between_0_and_1")

        if self.base_stop_loss_usd <= 0:
            raise ValueError("base_stop_loss_must_be_positive")

        if self.base_take_profit_usd <= 0:
            raise ValueError("base_take_profit_must_be_positive")

        if self.minimum_stop_loss_usd <= 0:
            raise ValueError("minimum_stop_loss_must_be_positive")

        if self.maximum_stop_loss_usd < self.minimum_stop_loss_usd:
            raise ValueError("maximum_stop_loss_below_minimum")

        if self.minimum_take_profit_usd <= 0:
            raise ValueError("minimum_take_profit_must_be_positive")

        if self.maximum_take_profit_usd < self.minimum_take_profit_usd:
            raise ValueError("maximum_take_profit_below_minimum")

        if not 0 < self.reversal_close_strength <= 1:
            raise ValueError("invalid_reversal_close_strength")

        if not 0 < self.profit_lock_fraction <= 1:
            raise ValueError("profit_lock_fraction_must_be_between_0_and_1")

        if self.profit_lock_start_usd < 0:
            raise ValueError("profit_lock_start_cannot_be_negative")

    # ------------------------------------------------------------------
    # Existing entry-risk interface
    # ------------------------------------------------------------------

    def allow_entry(
        self,
        initial_equity,
        equity,
        open_count,
        free_margin,
        required_margin,
        spread,
        commission,
        expected_move,
    ):
        """
        Compatibility interface used by the existing trading layer.

        `spread` and `commission` must use the same monetary units as
        `expected_move`. No fixed spread-pip ceiling is applied.
        """
        if expected_move <= 0:
            return False

        if required_margin < 0 or free_margin < 0:
            return False

        if breaker_triggered(
            initial_equity,
            equity,
            self.drawdown_limit,
        ):
            return False

        if not can_open_new_position(
            open_count,
            self.max_positions,
            equity,
            free_margin,
            required_margin,
        ):
            return False

        return cost_ratio(
            spread,
            commission,
            expected_move,
        ) <= self.max_cost_ratio

    # ------------------------------------------------------------------
    # Adaptive per-position management
    # ------------------------------------------------------------------

    @staticmethod
    def _money_to_price_distance(
        money,
        volume,
        usd_per_price_unit_per_lot,
    ):
        """
        Convert account-currency money into a price distance using the
        broker-provided contract value.
        """
        denominator = volume * usd_per_price_unit_per_lot

        if denominator <= 0:
            raise ValueError("invalid_contract_value")

        return max(0.0, float(money)) / denominator

    @staticmethod
    def _directional_price(entry_price, direction, distance):
        if direction == "BUY":
            return entry_price + distance
        return entry_price - distance

    @staticmethod
    def _stop_is_more_protective(direction, candidate, current):
        """
        True only when candidate tightens the stop.

        BUY stop: higher is more protective.
        SELL stop: lower is more protective.
        """
        if current is None:
            return True

        if direction == "BUY":
            return candidate > current

        return candidate < current

    @staticmethod
    def _tp_is_farther_in_profit(direction, candidate, current):
        """
        True only when candidate extends TP in the profitable direction.
        """
        if current is None:
            return True

        if direction == "BUY":
            return candidate > current

        return candidate < current

    def manage_position(
        self,
        position: PositionState,
        market: MarketState,
    ) -> PositionDecision:
        """
        Generate an adaptive decision for one open position.

        The caller should run this for every position on each relevant
        market update, then submit modifications through the broker
        execution layer.

        Stops are monotonic: this function never loosens an existing SL.
        """

        direction = position.direction.upper()

        signed_momentum = (
            market.momentum
            if direction == "BUY"
            else -market.momentum
        )

        # Reversal evidence is interpreted relative to the position.
        reversal_against_position = (
            market.reversal_strength
            if signed_momentum >= 0
            else min(1.0, market.reversal_strength + 0.15)
        )

        # Strong validated continuation can extend the target.
        continuation = market.continuation_strength
        momentum_alignment = max(0.0, min(1.0, signed_momentum / 10.0))
        continuation_score = continuation * momentum_alignment

        # Do not extend a target when expected reward cannot reasonably
        # cover the current estimated execution cost.
        reward_cost_ratio = (
            market.expected_move_usd / market.execution_cost_usd
            if market.execution_cost_usd > 0
            else float("inf")
        )

        # Strong reversal: exit rather than waiting for the original TP.
        if (
            reversal_against_position >= self.reversal_close_strength
            and position.profit_usd > 0
        ):
            return PositionDecision(
                action=PositionAction.CLOSE,
                reason="strong_reversal_protect_profit",
                desired_sl_price=position.current_sl_price,
                desired_tp_price=position.current_tp_price,
                lock_profit_usd=max(0.0, position.profit_usd),
                estimated_remaining_reward_usd=0.0,
            )

        # Calculate a baseline monetary SL and TP using the original
        # target ranges. This preserves the original style of small,
        # fast gold scalping targets.
        stop_money = max(
            self.minimum_stop_loss_usd,
            min(
                self.maximum_stop_loss_usd,
                self.base_stop_loss_usd,
            ),
        )

        target_money = max(
            self.minimum_take_profit_usd,
            min(
                self.maximum_take_profit_usd,
                self.base_take_profit_usd,
            ),
        )

        # Tighten risk when momentum weakens or reversal evidence grows.
        weakness = max(
            1.0 - continuation_score,
            reversal_against_position,
        )

        if weakness >= 0.70:
            stop_money *= 0.65
        elif weakness >= 0.50:
            stop_money *= 0.80

        stop_money = max(
            self.minimum_stop_loss_usd,
            min(self.maximum_stop_loss_usd, stop_money),
        )

        # Extend TP only when direction, continuation and expected
        # remaining reward support it.
        if (
            continuation_score >= 0.70
            and reward_cost_ratio >= self.minimum_reward_cost_ratio
            and market.expected_move_usd > target_money
        ):
            extension = 1.0 + (continuation_score - 0.70) * 2.0
            target_money = min(
                self.maximum_take_profit_usd,
                max(target_money, market.expected_move_usd * extension),
            )

        # Convert target and stop distances into broker-price units.
        stop_distance = self._money_to_price_distance(
            stop_money,
            position.volume,
            position.usd_per_price_unit_per_lot,
        )

        target_distance = self._money_to_price_distance(
            target_money,
            position.volume,
            position.usd_per_price_unit_per_lot,
        )

        candidate_sl = self._directional_price(
            position.entry_price,
            direction,
            -stop_distance if direction == "BUY" else stop_distance,
        )

        candidate_tp = self._directional_price(
            position.entry_price,
            direction,
            target_distance,
        )

        # Lock part of peak profit after the position has earned enough.
        lock_profit = 0.0

        peak_profit = max(
            position.peak_profit_usd,
            position.profit_usd,
        )

        if peak_profit >= self.profit_lock_start_usd:
            lock_profit = peak_profit * self.profit_lock_fraction

            lock_distance = self._money_to_price_distance(
                lock_profit,
                position.volume,
                position.usd_per_price_unit_per_lot,
            )

            locked_stop = self._directional_price(
                position.entry_price,
                direction,
                lock_distance,
            )

            if self._stop_is_more_protective(
                direction,
                locked_stop,
                candidate_sl,
            ):
                candidate_sl = locked_stop

        # Existing SL may only become more protective.
        if not self._stop_is_more_protective(
            direction,
            candidate_sl,
            position.current_sl_price,
        ):
            candidate_sl = position.current_sl_price

        # Existing TP may be extended in the profitable direction,
        # but this module does not pull it farther away when conditions
        # weaken. The execution/exit layer may close earlier.
        if not self._tp_is_farther_in_profit(
            direction,
            candidate_tp,
            position.current_tp_price,
        ):
            candidate_tp = position.current_tp_price

        sl_changed = (
            position.current_sl_price is None
            or candidate_sl != position.current_sl_price
        )

        tp_changed = (
            position.current_tp_price is None
            or candidate_tp != position.current_tp_price
        )

        if sl_changed or tp_changed:
            return PositionDecision(
                action=PositionAction.MODIFY_PROTECTION,
                reason="adaptive_position_protection",
                desired_sl_price=candidate_sl,
                desired_tp_price=candidate_tp,
                lock_profit_usd=lock_profit,
                estimated_remaining_reward_usd=market.expected_move_usd,
            )

        return PositionDecision(
            action=PositionAction.HOLD,
            reason="protection_already_current",
            desired_sl_price=position.current_sl_price,
            desired_tp_price=position.current_tp_price,
            lock_profit_usd=lock_profit,
            estimated_remaining_reward_usd=market.expected_move_usd,
        )
