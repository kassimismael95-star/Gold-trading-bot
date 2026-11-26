
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_position_value(position, *names, default=None):
    """Read a value from either a dictionary or an SDK position object."""
    for name in names:
        if isinstance(position, dict):
            value = position.get(name)
        else:
            value = getattr(position, name, None)

        if value is not None:
            return value

    return default


@dataclass
class PositionState:
    position_id: str
    account_id: str
    symbol: str
    direction: str
    entry_price: float
    volume: float

    initial_stop_loss: Optional[float] = None
    initial_take_profit: Optional[float] = None

    current_stop_loss: Optional[float] = None
    current_take_profit: Optional[float] = None

    highest_favourable_price: Optional[float] = None
    lowest_favourable_price: Optional[float] = None

    maximum_unrealised_profit: float = 0.0
    current_unrealised_profit: float = 0.0

    momentum_state: str = "UNASSESSED"
    reversal_state: str = "UNASSESSED"
    management_state: str = "ACTIVE"

    last_modified_at: Optional[str] = None
    last_partial_close_at: Optional[str] = None
    last_management_reason: Optional[str] = None
    exit_reason: Optional[str] = None

    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


class PositionManager:
    """
    Tracks and manages individual broker positions.

    This class does not open trades and does not make independent
    market predictions. The Master Live Market Controller supplies
    management decisions.

    Broker execution and confirmation remain the controller's job.
    """

    def __init__(self):
        self.positions: Dict[str, PositionState] = {}

    @staticmethod
    def _normalise_direction(direction):
        direction = str(direction).upper()

        if direction in ("BUY", "LONG"):
            return "BUY"

        if direction in ("SELL", "SHORT"):
            return "SELL"

        raise ValueError("Unsupported position direction")

    @staticmethod
    def _optional_float(value):
        if value is None:
            return None
        return float(value)

    def register_position(
        self,
        position_id,
        account_id,
        symbol,
        direction,
        entry_price,
        volume,
        stop_loss=None,
        take_profit=None
    ):
        """
        Register a broker-confirmed position.

        Re-registering an existing position updates its broker
        details without resetting its recorded profit history.
        """
        position_id = str(position_id)
        account_id = str(account_id)

        direction = self._normalise_direction(direction)
        entry_price = float(entry_price)
        volume = float(volume)

        if entry_price <= 0 or volume <= 0:
            raise ValueError("Entry price and volume must be positive")

        existing = self.positions.get(position_id)

        if existing:
            if existing.account_id != account_id:
                raise ValueError("Position account ownership mismatch")

            existing.volume = volume
            existing.current_stop_loss = self._optional_float(stop_loss)
            existing.current_take_profit = self._optional_float(take_profit)
            existing.updated_at = utc_now()
            return existing

        state = PositionState(
            position_id=position_id,
            account_id=account_id,
            symbol=str(symbol),
            direction=direction,
            entry_price=entry_price,
            volume=volume,
            initial_stop_loss=self._optional_float(stop_loss),
            initial_take_profit=self._optional_float(take_profit),
            current_stop_loss=self._optional_float(stop_loss),
            current_take_profit=self._optional_float(take_profit),
            highest_favourable_price=entry_price,
            lowest_favourable_price=entry_price
        )

        self.positions[position_id] = state
        return state

    def register_broker_position(self, account_id, position):
        """Register a position returned by the broker SDK."""
        position_id = get_position_value(
            position, "id", "position_id", "ticket"
        )

        if position_id is None:
            raise ValueError("Broker position has no identifiable ID")

        symbol = get_position_value(position, "symbol", default="")
        raw_type = get_position_value(
            position, "type", "trade_type", "direction", default=""
        )

        raw_type = str(raw_type).upper()

        if raw_type in ("0", "BUY", "LONG", "POSITION_TYPE_BUY"):
            direction = "BUY"
        elif raw_type in ("1", "SELL", "SHORT", "POSITION_TYPE_SELL"):
            direction = "SELL"
        else:
            raise ValueError("Cannot determine broker position direction")

        return self.register_position(
            position_id=position_id,
            account_id=account_id,
            symbol=symbol,
            direction=direction,
            entry_price=get_position_value(
                position, "open_price", "entry_price", "price"
            ),
            volume=get_position_value(position, "volume", "lots"),
            stop_loss=get_position_value(position, "stop_loss", "sl"),
            take_profit=get_position_value(position, "take_profit", "tp")
        )

    def update_market_state(
        self,
        position_id,
        current_price,
        unrealised_profit,
        momentum_state=None,
        reversal_state=None
    ):
        """Update the live market and profit information for one position."""
        state = self._get(position_id)

        current_price = float(current_price)
        unrealised_profit = float(unrealised_profit)

        if current_price <= 0:
            raise ValueError("Current price must be positive")

        state.current_unrealised_profit = unrealised_profit

        state.maximum_unrealised_profit = max(
            state.maximum_unrealised_profit,
            unrealised_profit
        )

        if state.direction == "BUY":
            state.highest_favourable_price = max(
                state.highest_favourable_price or current_price,
                current_price
            )
        else:
            state.lowest_favourable_price = min(
                state.lowest_favourable_price or current_price,
                current_price
            )

        if momentum_state is not None:
            state.momentum_state = str(momentum_state)

        if reversal_state is not None:
            state.reversal_state = str(reversal_state)

        state.updated_at = utc_now()
        return state

    def create_management_plan(
        self,
        position_id,
        new_stop_loss=None,
        new_take_profit=None,
        partial_close_volume=None,
        close_position=False,
        reason=None
    ):
        """
        Validate a management proposal from the Master Controller.

        BUY stop losses may move upward, never downward.
        SELL stop losses may move downward, never upward.

        Take-profit changes are allowed in either direction.
        The controller determines the appropriate target.

        This method creates a plan; it does not execute broker actions.
        """
        state = self._get(position_id)

        plan = {
            "position_id": state.position_id,
            "account_id": state.account_id,
            "symbol": state.symbol,
            "close_position": bool(close_position),
            "partial_close_volume": None,
            "stop_loss": None,
            "take_profit": None,
            "reason": reason,
            "created_at": utc_now()
        }

        if close_position:
            plan["reason"] = reason or "controller_close_decision"
            return plan

        if new_stop_loss is not None:
            proposed_sl = float(new_stop_loss)

            if proposed_sl <= 0:
                raise ValueError("Stop loss must be positive")

            current_sl = state.current_stop_loss

            if current_sl is None:
                plan["stop_loss"] = proposed_sl

            elif state.direction == "BUY" and proposed_sl > current_sl:
                plan["stop_loss"] = proposed_sl

            elif state.direction == "SELL" and proposed_sl < current_sl:
                plan["stop_loss"] = proposed_sl

        if new_take_profit is not None:
            proposed_tp = float(new_take_profit)

            if proposed_tp <= 0:
                raise ValueError("Take profit must be positive")

            plan["take_profit"] = proposed_tp

        if partial_close_volume is not None:
            partial_volume = float(partial_close_volume)

            if partial_volume <= 0:
                raise ValueError("Partial close volume must be positive")

            if partial_volume >= state.volume:
                raise ValueError(
                    "Partial close must be smaller than remaining volume"
                )

            plan["partial_close_volume"] = partial_volume

        plan["reason"] = reason or "controller_management"
        return plan

    def confirm_broker_update(
        self,
        position_id,
        stop_loss=None,
        take_profit=None,
        remaining_volume=None,
        partial_close=False
    ):
        """
        Update internal state only after broker state confirms the change.
        """
        state = self._get(position_id)

        if stop_loss is not None:
            state.current_stop_loss = float(stop_loss)

        if take_profit is not None:
            state.current_take_profit = float(take_profit)

        if remaining_volume is not None:
            state.volume = float(remaining_volume)

        if partial_close:
            state.last_partial_close_at = utc_now()

        state.last_modified_at = utc_now()
        state.updated_at = utc_now()

        return state

    def mark_closed(self, position_id, exit_reason):
        """Mark a position closed after broker confirmation."""
        state = self._get(position_id)

        state.management_state = "CLOSED"
        state.exit_reason = str(exit_reason)
        state.updated_at = utc_now()

        return state

    def remove_closed_position(self, position_id):
        """Remove a position only after closure has been verified."""
        position_id = str(position_id)
        state = self.positions.get(position_id)

        if state is None:
            return False

        if state.management_state != "CLOSED":
            raise ValueError("Cannot remove an unconfirmed open position")

        del self.positions[position_id]
        return True

    def get_position(self, position_id):
        return self._get(position_id)

    def get_account_positions(self, account_id):
        account_id = str(account_id)

        return {
            position_id: state
            for position_id, state in self.positions.items()
            if state.account_id == account_id
            and state.management_state != "CLOSED"
        }

    def get_all_active_positions(self):
        return {
            position_id: state
            for position_id, state in self.positions.items()
            if state.management_state != "CLOSED"
        }

    def _get(self, position_id):
        position_id = str(position_id)

        state = self.positions.get(position_id)

        if state is None:
            raise KeyError(
                f"Position {position_id} is not registered"
            )

        return state
