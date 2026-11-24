import time
from dataclasses import dataclass, field


@dataclass
class BotRuntimeState:
    last_batch_entry_price: float = 0.0
    last_batch_close_time: float = 0.0
    last_batch_direction: str | None = None


@dataclass
class MarketState:
    bid: float
    ask: float
    spread_pips: float
    free_margin: float
    balance: float
    equity: float
    open_positions: list[dict] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    action: str
    direction: str | None = None
    volume: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    position_number: int = 0
    reason: str = ""


class BotManager:
    """
    Exact original Gold Scalper balanced multi-position engine.

    Preserves:
    - First-entry behavior
    - Add-position behavior
    - Basket profit-target close
    - 35% drawdown circuit breaker
    - Original polling and burst delays
    """

    POLL_LATENCY_DELAY = 0.05
    BURST_SPACING_DELAY = 0.08
    MULTI_SCALP_COOLDOWN_SECONDS = 3

    def __init__(self, risk_manager, signal_tracker):
        self.risk_manager = risk_manager
        self.signal_tracker = signal_tracker
        self.state = BotRuntimeState()

    def reset_batch(self) -> None:
        self.state.last_batch_entry_price = 0.0
        self.state.last_batch_close_time = time.time()
        self.state.last_batch_direction = None

    def can_start_new_batch(self) -> bool:
        seconds_since_close = time.time() - self.state.last_batch_close_time

        return seconds_since_close >= self.MULTI_SCALP_COOLDOWN_SECONDS

    def decide(
        self,
        market: MarketState,
        direction: str,
        confidence: int,
        recent_price_movement: float,
    ) -> ExecutionPlan:
        basket_positions = [
            position
            for position in market.open_positions
            if position.get("symbol") == market.symbol
        ]

        open_position_count = len(basket_positions)

        basket_profit = 0.0

        for position in basket_positions:
            basket_profit += float(position.get("profit", 0) or 0)

        basket_profit = round(basket_profit, 2)

        net_floating_profit = market.equity - market.balance

        if open_position_count > 0:
            if self.risk_manager.should_close_basket_by_profit(
                basket_profit,
                market.equity,
                market.balance,
                confidence,
            ):
                return ExecutionPlan(
                    action="CLOSE_BASKET",
                    reason=(
                        f"Basket profit target reached: "
                        f"+{basket_profit:.2f} USD."
                    ),
                )

            if self.risk_manager.should_trigger_drawdown_circuit_breaker(
                market.balance,
                net_floating_profit,
            ):
                return ExecutionPlan(
                    action="CLOSE_BASKET",
                    reason=(
                        f"35% drawdown circuit breaker reached: "
                        f"-{abs(net_floating_profit):.2f} USD."
                    ),
                )

            if self.risk_manager.can_add_position(
                basket_profit=basket_profit,
                price_progress=self.calculate_price_progress(market),
                current_spread_pips=market.spread_pips,
                free_margin=market.free_margin,
                open_position_count=open_position_count,
                equity=market.equity,
                balance=market.balance,
                confidence_score=confidence,
            ):
                basket_plan = self.risk_manager.calculate_video_dynamic_burst(
                    market.equity,
                    market.balance,
                    confidence,
                )

                added_lot = self.risk_manager.calculate_added_position_lot(
                    market.equity,
                    market.balance,
                    confidence,
                    open_position_count + 1,
                )

                entry_price = (
                    market.ask
                    if self.state.last_batch_direction == "BUY"
                    else market.bid
                )

                risk_plan = self.risk_manager.calculate_dynamic_tp_sl(
                    direction=self.state.last_batch_direction,
                    entry_price=entry_price,
                    current_spread_pips=market.spread_pips,
                    confidence_score=confidence,
                    position_number=open_position_count + 1,
                    recent_price_movement=recent_price_movement,
                )

                return ExecutionPlan(
                    action="OPEN_POSITION",
                    direction=self.state.last_batch_direction,
                    volume=added_lot,
                    stop_loss=risk_plan.stop_loss,
                    take_profit=risk_plan.take_profit,
                    position_number=open_position_count + 1,
                    reason=(
                        f"Adding balanced position #{open_position_count + 1}; "
                        f"basket profit +{basket_profit:.2f} USD; "
                        f"max positions {basket_plan.max_positions}."
                    ),
                )

            return ExecutionPlan(
                action="HOLD",
                reason=(
                    "Existing basket is active; waiting for basket profit, "
                    "price progress, spread, margin, or position-limit conditions."
                ),
            )

        if not self.can_start_new_batch():
            return ExecutionPlan(
                action="HOLD",
                reason="Multi-scalp cooldown is still active.",
            )

        if market.spread_pips > self.risk_manager.MAX_ALLOWED_SPREAD_PIPS:
            return ExecutionPlan(
                action="HOLD",
                reason=(
                    f"Spread {market.spread_pips:.2f} pips exceeds "
                    f"{self.risk_manager.MAX_ALLOWED_SPREAD_PIPS:.2f} pips."
                ),
            )

        if direction not in ["BUY", "SELL"]:
            return ExecutionPlan(
                action="HOLD",
                reason="Momentum direction is not actionable.",
            )

        basket_plan = self.risk_manager.calculate_video_dynamic_burst(
            market.equity,
            market.balance,
            confidence,
        )

        entry_price = (
            market.ask if direction == "BUY" else market.bid
        )

        risk_plan = self.risk_manager.calculate_dynamic_tp_sl(
            direction=direction,
            entry_price=entry_price,
            current_spread_pips=market.spread_pips,
            confidence_score=confidence,
            position_number=1,
            recent_price_movement=recent_price_movement,
        )

        return ExecutionPlan(
            action="OPEN_POSITION",
            direction=direction,
            volume=basket_plan.first_lot,
            stop_loss=risk_plan.stop_loss,
            take_profit=risk_plan.take_profit,
            position_number=1,
            reason=(
                f"First balanced entry; confidence {confidence}; "
                f"lot {basket_plan.first_lot}; "
                f"max positions {basket_plan.max_positions}; "
                f"basket target {basket_plan.basket_profit_target:.2f} USD."
            ),
        )

    def calculate_price_progress(self, market: MarketState) -> float:
        current_price = (market.ask + market.bid) / 2.0

        if self.state.last_batch_direction == "BUY":
            return current_price - self.state.last_batch_entry_price

        if self.state.last_batch_direction == "SELL":
            return self.state.last_batch_entry_price - current_price

        return 0.0

    def register_first_entry(self, direction: str, market: MarketState) -> None:
        current_price = (market.ask + market.bid) / 2.0

        self.state.last_batch_entry_price = current_price
        self.state.last_batch_direction = direction
        self.state.last_batch_close_time = time.time()

    def register_added_entry(self, market: MarketState) -> None:
        current_price = (market.ask + market.bid) / 2.0

        self.state.last_batch_entry_price = current_price
