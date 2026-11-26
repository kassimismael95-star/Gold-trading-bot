
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TradingBasket:
    basket_id: str
    account_id: str
    symbol: str

    profit_target: float

    position_ids: list = field(default_factory=list)

    floating_profit: float = 0.0
    realised_profit: float = 0.0

    status: str = "ACTIVE"

    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    close_requested: bool = False
    close_reason: Optional[str] = None


class BasketManager:
    """
    Tracks trading baskets independently from individual positions.

    This component:
    - Does not open positions.
    - Does not change original entry rules.
    - Does not invent basket profit targets.
    - Does not execute broker orders itself.

    The calling execution layer must verify basket closures
    against actual broker positions.
    """

    def __init__(self):
        self.baskets: Dict[str, TradingBasket] = {}
        self.position_to_basket: Dict[str, str] = {}

    def create_basket(
        self,
        basket_id,
        account_id,
        symbol,
        profit_target
    ):
        basket_id = str(basket_id)
        account_id = str(account_id)

        if basket_id in self.baskets:
            raise ValueError("Basket already exists")

        profit_target = float(profit_target)

        if profit_target < 0:
            raise ValueError("Basket target cannot be negative")

        basket = TradingBasket(
            basket_id=basket_id,
            account_id=account_id,
            symbol=str(symbol),
            profit_target=profit_target
        )

        self.baskets[basket_id] = basket

        return basket

    def add_position(self, basket_id, position_id):
        basket_id = str(basket_id)
        position_id = str(position_id)

        basket = self._get_basket(basket_id)

        if basket.status != "ACTIVE":
            raise ValueError("Cannot add positions to an inactive basket")

        existing_basket = self.position_to_basket.get(position_id)

        if existing_basket is not None:
            if existing_basket == basket_id:
                return basket

            raise ValueError(
                "Position already belongs to another basket"
            )

        basket.position_ids.append(position_id)
        self.position_to_basket[position_id] = basket_id

        basket.updated_at = utc_now()

        return basket

    def remove_position(self, basket_id, position_id):
        basket_id = str(basket_id)
        position_id = str(position_id)

        basket = self._get_basket(basket_id)

        if position_id in basket.position_ids:
            basket.position_ids.remove(position_id)

        if self.position_to_basket.get(position_id) == basket_id:
            del self.position_to_basket[position_id]

        basket.updated_at = utc_now()

        return basket

    def update_position_profit(
        self,
        position_id,
        floating_profit
    ):
        position_id = str(position_id)

        basket_id = self.position_to_basket.get(position_id)

        if basket_id is None:
            raise KeyError("Position is not assigned to a basket")

        basket = self._get_basket(basket_id)

        # The basket total is recalculated from its latest
        # known position-profit observations.
        basket_position_profits = getattr(
            basket,
            "_position_profits",
            {}
        )

        basket_position_profits[position_id] = float(
            floating_profit
        )

        basket._position_profits = basket_position_profits

        basket.floating_profit = sum(
            basket_position_profits.values()
        )

        basket.updated_at = utc_now()

        return basket

    def add_realised_profit(
        self,
        position_id,
        realised_profit
    ):
        position_id = str(position_id)

        basket_id = self.position_to_basket.get(position_id)

        if basket_id is None:
            raise KeyError("Position is not assigned to a basket")

        basket = self._get_basket(basket_id)

        basket.realised_profit += float(realised_profit)

        basket.updated_at = utc_now()

        return basket

    def evaluate_basket(self, basket_id):
        """
        Check whether the original basket profit target has been reached.

        The result is a close request, not a broker execution confirmation.
        """
        basket = self._get_basket(basket_id)

        if basket.status != "ACTIVE":
            return {
                "basket_id": basket.basket_id,
                "action": "none",
                "reason": "basket_not_active"
            }

        if basket.floating_profit >= basket.profit_target:
            basket.close_requested = True
            basket.close_reason = "original_basket_profit_target_reached"
            basket.updated_at = utc_now()

            return {
                "basket_id": basket.basket_id,
                "account_id": basket.account_id,
                "action": "close_basket",
                "reason": basket.close_reason,
                "position_ids": list(basket.position_ids),
                "floating_profit": basket.floating_profit,
                "profit_target": basket.profit_target
            }

        return {
            "basket_id": basket.basket_id,
            "account_id": basket.account_id,
            "action": "continue",
            "floating_profit": basket.floating_profit,
            "profit_target": basket.profit_target,
            "remaining_to_target": (
                basket.profit_target - basket.floating_profit
            )
        }

    def confirm_basket_closed(
        self,
        basket_id,
        broker_open_position_ids
    ):
        """
        Mark a basket closed only when the broker confirms
        that none of its positions remain open.
        """
        basket = self._get_basket(basket_id)

        broker_open_ids = {
            str(position_id)
            for position_id in broker_open_position_ids
        }

        remaining = [
            position_id
            for position_id in basket.position_ids
            if position_id in broker_open_ids
        ]

        if remaining:
            raise RuntimeError(
                "Basket still has broker-confirmed open positions"
            )

        basket.status = "CLOSED"
        basket.floating_profit = 0.0
        basket.updated_at = utc_now()

        for position_id in list(basket.position_ids):
            if self.position_to_basket.get(position_id) == basket.basket_id:
                del self.position_to_basket[position_id]

        basket.position_ids.clear()

        return {
            "basket_id": basket.basket_id,
            "status": basket.status,
            "realised_profit": basket.realised_profit,
            "verified": True
        }

    def get_basket(self, basket_id):
        return self._get_basket(basket_id)

    def get_account_baskets(self, account_id):
        account_id = str(account_id)

        return {
            basket_id: basket
            for basket_id, basket in self.baskets.items()
            if basket.account_id == account_id
        }

    def get_active_baskets(self, account_id=None):
        account_id = (
            str(account_id)
            if account_id is not None else None
        )

        return {
            basket_id: basket
            for basket_id, basket in self.baskets.items()
            if basket.status == "ACTIVE"
            and (
                account_id is None
                or basket.account_id == account_id
            )
        }

    def get_position_basket(self, position_id):
        basket_id = self.position_to_basket.get(str(position_id))

        if basket_id is None:
            return None

        return self.baskets.get(basket_id)

    def _get_basket(self, basket_id):
        basket_id = str(basket_id)

        basket = self.baskets.get(basket_id)

        if basket is None:
            raise KeyError(
                f"Basket {basket_id} is not registered"
            )

        return basket
