
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MarketObservation:
    timestamp: str
    bid: float
    ask: float
    mid: float
    spread: float


class MarketIntelligence:
    """
    Live market observation and position-management decision layer.

    It does not open positions.
    It does not change the original entry strategy.
    It does not invent fixed profit, spread, drawdown or reversal
    thresholds.

    Position decisions are produced by an injected policy.
    """

    def __init__(
        self,
        position_policy=None,
        account_policy=None,
        history_size=500
    ):
        self.position_policy = position_policy
        self.account_policy = account_policy

        self.history_size = int(history_size)

        if self.history_size < 3:
            raise ValueError("Market history must hold at least 3 observations")

        self.market_history = {}
        self.last_position_decisions = {}
        self.last_account_decisions = {}

    def _history(self, account_id, symbol):
        key = (str(account_id), str(symbol))

        if key not in self.market_history:
            self.market_history[key] = deque(
                maxlen=self.history_size
            )

        return self.market_history[key]

    def record_tick(self, account_id, symbol, bid, ask):
        """
        Record a valid broker tick and calculate its midpoint and spread.
        """
        bid = float(bid)
        ask = float(ask)

        if bid <= 0 or ask <= 0:
            raise ValueError("Bid and ask must be positive")

        if ask < bid:
            raise ValueError("Ask cannot be lower than bid")

        observation = MarketObservation(
            timestamp=utc_now(),
            bid=bid,
            ask=ask,
            mid=(bid + ask) / 2.0,
            spread=ask - bid
        )

        history = self._history(account_id, symbol)
        history.append(observation)

        return observation

    def get_market_snapshot(self, account_id, symbol):
        """
        Return the latest market observation and available history.
        """
        history = self._history(account_id, symbol)

        if not history:
            return None

        observations = list(history)

        prices = [item.mid for item in observations]

        return {
            "account_id": str(account_id),
            "symbol": str(symbol),
            "timestamp": observations[-1].timestamp,
            "bid": observations[-1].bid,
            "ask": observations[-1].ask,
            "mid": observations[-1].mid,
            "spread": observations[-1].spread,
            "history_count": len(observations),
            "prices": prices,
            "observations": [
                {
                    "timestamp": item.timestamp,
                    "bid": item.bid,
                    "ask": item.ask,
                    "mid": item.mid,
                    "spread": item.spread
                }
                for item in observations
            ]
        }

    @staticmethod
    def calculate_price_changes(snapshot):
        """
        Calculate observed price changes without imposing a
        directional trading threshold.
        """
        prices = snapshot.get("prices", [])

        if len(prices) < 2:
            return {
                "latest_change": None,
                "total_change": None,
                "highest_price": None,
                "lowest_price": None
            }

        return {
            "latest_change": prices[-1] - prices[-2],
            "total_change": prices[-1] - prices[0],
            "highest_price": max(prices),
            "lowest_price": min(prices)
        }

    @staticmethod
    def calculate_position_metrics(position, snapshot):
        """
        Calculate the live price relationship for an individual position.
        """
        current_price = float(snapshot["mid"])
        entry_price = float(position.entry_price)

        if position.direction == "BUY":
            favourable_move = current_price - entry_price
            adverse_move = entry_price - current_price
            favourable_extreme = position.highest_favourable_price

        elif position.direction == "SELL":
            favourable_move = entry_price - current_price
            adverse_move = current_price - entry_price
            favourable_extreme = position.lowest_favourable_price

        else:
            raise ValueError("Unknown position direction")

        return {
            "position_id": position.position_id,
            "account_id": position.account_id,
            "symbol": position.symbol,
            "direction": position.direction,
            "entry_price": entry_price,
            "current_price": current_price,
            "volume": position.volume,
            "favourable_price_movement": favourable_move,
            "adverse_price_movement": adverse_move,
            "favourable_extreme": favourable_extreme,
            "current_unrealised_profit": (
                position.current_unrealised_profit
            ),
            "maximum_unrealised_profit": (
                position.maximum_unrealised_profit
            ),
            "current_stop_loss": position.current_stop_loss,
            "current_take_profit": position.current_take_profit,
            "market": snapshot
        }

    async def evaluate_position(self, position, snapshot):
        """
        Ask the configured intelligence policy to assess one position.

        The policy receives position metrics and market observations.
        """
        if self.position_policy is None:
            raise RuntimeError(
                "Position intelligence policy is not configured"
            )

        metrics = self.calculate_position_metrics(
            position,
            snapshot
        )

        decision = self.position_policy(metrics)

        if hasattr(decision, "__await__"):
            decision = await decision

        if not isinstance(decision, dict):
            raise TypeError(
                "Position policy must return a dictionary"
            )

        allowed_fields = {
            "momentum_state",
            "reversal_state",
            "stop_loss",
            "take_profit",
            "partial_close_volume",
            "close_position",
            "reason"
        }

        unknown_fields = set(decision) - allowed_fields

        if unknown_fields:
            raise ValueError(
                f"Unsupported position decision fields: {unknown_fields}"
            )

        result = {
            "position_id": position.position_id,
            "account_id": position.account_id,
            "symbol": position.symbol,
            "metrics": metrics,
            "decision": decision,
            "evaluated_at": utc_now()
        }

        self.last_position_decisions[position.position_id] = result

        return decision

    async def evaluate_account(self, account_snapshot):
        """
        Ask the configured account policy to assess combined account risk.
        """
        if self.account_policy is None:
            raise RuntimeError(
                "Account intelligence policy is not configured"
            )

        decision = self.account_policy(account_snapshot)

        if hasattr(decision, "__await__"):
            decision = await decision

        if not isinstance(decision, dict):
            raise TypeError(
                "Account policy must return a dictionary"
            )

        allowed_actions = {
            "none",
            "block_new_entries",
            "reduce_exposure",
            "close_position",
            "close_basket"
        }

        action = str(decision.get("action", "none")).lower()

        if action not in allowed_actions:
            raise ValueError("Unsupported account risk action")

        result = {
            "account_id": str(account_snapshot["account_id"]),
            "action": action,
            "reason": decision.get("reason"),
            "position_ids": decision.get("position_ids", []),
            "reductions": decision.get("reductions"),
            "evaluated_at": utc_now()
        }

        self.last_account_decisions[
            result["account_id"]
        ] = result

        return decision

    def get_last_position_decision(self, position_id):
        return self.last_position_decisions.get(str(position_id))

    def get_last_account_decision(self, account_id):
        return self.last_account_decisions.get(str(account_id))

    def clear_account_history(self, account_id):
        account_id = str(account_id)

        keys = [
            key for key in self.market_history
            if key[0] == account_id
        ]

        for key in keys:
            del self.market_history[key]

        position_ids = [
            position_id
            for position_id, result in self.last_position_decisions.items()
            if result["account_id"] == account_id
        ]

        for position_id in position_ids:
            del self.last_position_decisions[position_id]

        self.last_account_decisions.pop(account_id, None)
