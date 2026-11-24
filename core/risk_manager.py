from dataclasses import dataclass


@dataclass
class BasketPlan:
    first_lot: float
    max_positions: int
    basket_profit_target: float


@dataclass
class RiskPlan:
    direction: str
    entry_price: float
    volume: float
    stop_loss: float
    take_profit: float
    stop_loss_distance: float
    take_profit_distance: float
    reward_risk_ratio: float


class RiskManager:
    """
    Exact original Gold Scalper balanced multi-position risk logic.

    Preserves:
    - Capital-based first-position lot sizing
    - Capital-and-confidence-based added-position lot sizing
    - Dynamic basket profit targets
    - Dynamic SL/TP calculation
    - 35% balance drawdown circuit breaker
    - Maximum 18-position hard limit
    """

    MAX_ALLOWED_SPREAD_PIPS = 35.0
    ADD_POSITION_MOVE_USD = 0.15
    MULTI_SCALP_COOLDOWN_SECONDS = 3
    MAX_POSITIONS_HARD_LIMIT = 18

    BASE_STOP_LOSS_USD = 2.00
    BASE_TAKE_PROFIT_USD = 2.20

    MIN_STOP_LOSS_USD = 1.50
    MAX_STOP_LOSS_USD = 3.00

    MIN_TAKE_PROFIT_USD = 1.80
    MAX_TAKE_PROFIT_USD = 3.50

    DRAWDOWN_CIRCUIT_BREAKER_PERCENT = 35.0

    def calculate_video_dynamic_burst(
        self,
        equity: float,
        balance: float,
        confidence_score: int,
    ) -> BasketPlan:
        capital = max(equity, balance)
        abs_conf = abs(confidence_score)

        if capital < 4.0:
            max_positions = 2 if abs_conf >= 7 else 1
            return BasketPlan(0.01, max_positions, 0.35)

        elif capital < 10.0:
            max_positions = 3 if abs_conf >= 6 else 2
            return BasketPlan(0.01, max_positions, 0.50)

        elif capital < 25.0:
            max_positions = 5 if abs_conf >= 7 else 3
            return BasketPlan(0.02, max_positions, 1.00)

        elif capital < 50.0:
            max_positions = 7 if abs_conf >= 6 else 5
            return BasketPlan(0.03, max_positions, 2.00)

        elif capital < 100.0:
            max_positions = 9 if abs_conf >= 6 else 7
            return BasketPlan(0.04, max_positions, 4.00)

        elif capital < 250.0:
            max_positions = 12 if abs_conf >= 6 else 9
            return BasketPlan(0.06, max_positions, 8.00)

        elif capital < 500.0:
            max_positions = 14 if abs_conf >= 6 else 12
            return BasketPlan(0.10, max_positions, 15.00)

        elif capital < 1000.0:
            max_positions = 16 if abs_conf >= 6 else 14
            return BasketPlan(0.20, max_positions, 30.00)

        elif capital < 2000.0:
            max_positions = 18 if abs_conf >= 6 else 16
            return BasketPlan(0.35, max_positions, 60.00)

        elif capital < 5000.0:
            return BasketPlan(0.60, 18, 120.00)

        elif capital < 10000.0:
            return BasketPlan(1.00, 18, 250.00)

        elif capital < 25000.0:
            return BasketPlan(2.00, 18, 600.00)

        else:
            return BasketPlan(4.00, 18, 1500.00)

    def calculate_added_position_lot(
        self,
        equity: float,
        balance: float,
        confidence_score: int,
        position_number: int,
    ) -> float:
        capital = max(equity, balance)
        abs_conf = abs(confidence_score)

        if capital < 10:
            base_lot = 0.01

        elif capital < 25:
            base_lot = 0.02 if abs_conf >= 7 else 0.01

        elif capital < 50:
            base_lot = 0.03 if abs_conf >= 6 else 0.02

        elif capital < 100:
            base_lot = 0.04 if abs_conf >= 6 else 0.03

        elif capital < 250:
            base_lot = 0.06 if abs_conf >= 6 else 0.04

        elif capital < 500:
            base_lot = 0.10 if abs_conf >= 6 else 0.06

        elif capital < 1000:
            base_lot = 0.20 if abs_conf >= 6 else 0.10

        elif capital < 2000:
            base_lot = 0.35 if abs_conf >= 6 else 0.20

        elif capital < 5000:
            base_lot = 0.60 if abs_conf >= 6 else 0.35

        elif capital < 10000:
            base_lot = 1.00 if abs_conf >= 6 else 0.60

        elif capital < 25000:
            base_lot = 2.00 if abs_conf >= 6 else 1.00

        else:
            base_lot = 4.00 if abs_conf >= 6 else 2.00

        if capital >= 25:
            bonus = ((position_number - 1) // 2) * 0.01
            base_lot += bonus

        return round(base_lot, 2)

    def calculate_dynamic_tp_sl(
        self,
        direction: str,
        entry_price: float,
        current_spread_pips: float,
        confidence_score: int,
        position_number: int,
        recent_price_movement: float,
    ) -> RiskPlan:
        spread_usd = current_spread_pips * 0.10

        movement_multiplier = 1.0

        if recent_price_movement > 0.50:
            movement_multiplier = 1.30
        elif recent_price_movement > 0.25:
            movement_multiplier = 1.15
        elif recent_price_movement > 0.10:
            movement_multiplier = 1.05

        confidence_multiplier = 1.0

        if confidence_score >= 8:
            confidence_multiplier = 1.15
        elif confidence_score >= 6:
            confidence_multiplier = 1.08
        elif confidence_score <= 2:
            confidence_multiplier = 0.90

        position_adjustment = (position_number - 1) * 0.08

        stop_loss_distance = (
            self.BASE_STOP_LOSS_USD
            + (spread_usd * 0.50)
            + position_adjustment
        ) * movement_multiplier

        take_profit_distance = (
            self.BASE_TAKE_PROFIT_USD
            + (spread_usd * 0.30)
            + position_adjustment
        ) * movement_multiplier * confidence_multiplier

        stop_loss_distance = max(
            self.MIN_STOP_LOSS_USD,
            min(self.MAX_STOP_LOSS_USD, stop_loss_distance),
        )

        take_profit_distance = max(
            self.MIN_TAKE_PROFIT_USD,
            min(self.MAX_TAKE_PROFIT_USD, take_profit_distance),
        )

        if take_profit_distance < stop_loss_distance:
            take_profit_distance = stop_loss_distance

        if direction == "BUY":
            stop_loss = entry_price - stop_loss_distance
            take_profit = entry_price + take_profit_distance

        else:
            stop_loss = entry_price + stop_loss_distance
            take_profit = entry_price - take_profit_distance

        return RiskPlan(
            direction=direction,
            entry_price=round(entry_price, 2),
            volume=0.0,
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            stop_loss_distance=round(stop_loss_distance, 2),
            take_profit_distance=round(take_profit_distance, 2),
            reward_risk_ratio=round(
                take_profit_distance / stop_loss_distance,
                2,
            ),
        )

    def should_close_basket_by_profit(
        self,
        basket_profit: float,
        equity: float,
        balance: float,
        confidence_score: int,
    ) -> bool:
        if basket_profit <= 0:
            return False

        basket_plan = self.calculate_video_dynamic_burst(
            equity,
            balance,
            confidence_score,
        )

        return basket_profit >= basket_plan.basket_profit_target

    def should_trigger_drawdown_circuit_breaker(
        self,
        balance: float,
        net_floating_profit: float,
    ) -> bool:
        if balance <= 10.0:
            return False

        drawdown_limit = -(balance * self.DRAWDOWN_CIRCUIT_BREAKER_PERCENT / 100)

        return net_floating_profit < drawdown_limit

    def can_add_position(
        self,
        basket_profit: float,
        price_progress: float,
        current_spread_pips: float,
        free_margin: float,
        open_position_count: int,
        equity: float,
        balance: float,
        confidence_score: int,
    ) -> bool:
        basket_plan = self.calculate_video_dynamic_burst(
            equity,
            balance,
            confidence_score,
        )

        max_positions = min(
            basket_plan.max_positions,
            self.MAX_POSITIONS_HARD_LIMIT,
        )

        if open_position_count >= max_positions:
            return False

        return (
            basket_profit > 0
            and price_progress >= self.ADD_POSITION_MOVE_USD
            and current_spread_pips <= self.MAX_ALLOWED_SPREAD_PIPS
            and free_margin > 0
            )
