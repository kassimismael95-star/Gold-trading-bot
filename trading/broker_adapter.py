
import asyncio
import inspect
from typing import Any, Dict, Optional


class BrokerAdapterError(RuntimeError):
    """Raised when a broker operation fails or cannot be verified."""


class MetaApiBrokerAdapter:
    """
    Account-isolated adapter for MetaApi trade connections.

    Each account must be registered with its own connected
    MetaApi RPC connection.

    Supports:
    - Reading live positions
    - Reading account information
    - Reading symbol prices
    - Modifying individual position SL/TP
    - Closing individual positions
    - Partially closing individual positions
    - Opening BUY and SELL market orders

    This adapter does not contain entry strategy or risk rules.
    """

    def __init__(self):
        self.connections: Dict[str, Any] = {}
        self.account_metadata: Dict[str, dict] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def register_connection(
        self,
        account_id: str,
        connection: Any,
        symbol: Optional[str] = None
    ):
        account_id = str(account_id)

        if not account_id:
            raise ValueError("account_id is required")

        if connection is None:
            raise ValueError("MetaApi connection is required")

        self.connections[account_id] = connection
        self.account_metadata[account_id] = {
            "symbol": symbol
        }

        self._locks.setdefault(account_id, asyncio.Lock())

    def unregister_connection(self, account_id: str):
        account_id = str(account_id)

        self.connections.pop(account_id, None)
        self.account_metadata.pop(account_id, None)
        self._locks.pop(account_id, None)

    def is_registered(self, account_id: str) -> bool:
        return str(account_id) in self.connections

    def _connection(self, account_id):
        account_id = str(account_id)

        connection = self.connections.get(account_id)

        if connection is None:
            raise BrokerAdapterError(
                f"No MetaApi connection registered for account {account_id}"
            )

        return connection

    @staticmethod
    async def _resolve(value):
        if inspect.isawaitable(value):
            return await value
        return value

    @staticmethod
    def _read_value(obj, *names, default=None):
        for name in names:
            if isinstance(obj, dict):
                if name in obj:
                    return obj[name]
            else:
                value = getattr(obj, name, None)
                if value is not None:
                    return value

        return default

    async def get_positions(self, account_id):
        connection = self._connection(account_id)

        try:
            positions = await self._resolve(
                connection.get_positions()
            )

            if positions is None:
                raise BrokerAdapterError(
                    "Broker returned no position snapshot"
                )

            return list(positions)

        except Exception as exc:
            raise BrokerAdapterError(
                f"Unable to retrieve broker positions: {exc}"
            ) from exc

    async def get_account_information(self, account_id):
        connection = self._connection(account_id)

        try:
            information = await self._resolve(
                connection.get_account_information()
            )

            if information is None:
                raise BrokerAdapterError(
                    "Broker returned no account information"
                )

            return information

        except Exception as exc:
            raise BrokerAdapterError(
                f"Unable to retrieve account information: {exc}"
            ) from exc

    async def get_symbol_price(self, account_id, symbol=None):
        connection = self._connection(account_id)

        if not symbol:
            symbol = self.account_metadata.get(
                str(account_id), {}
            ).get("symbol")

        if not symbol:
            raise ValueError("Trading symbol is required")

        try:
            price = await self._resolve(
                connection.get_symbol_price(symbol)
            )

            if price is None:
                raise BrokerAdapterError(
                    "Broker returned no symbol price"
                )

            bid = self._read_value(price, "bid")
            ask = self._read_value(price, "ask")

            if bid is None or ask is None:
                raise BrokerAdapterError(
                    "Broker price is missing bid or ask"
                )

            bid = float(bid)
            ask = float(ask)

            if bid <= 0 or ask <= 0 or ask < bid:
                raise BrokerAdapterError(
                    "Broker returned an invalid bid/ask price"
                )

            return {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "mid": (bid + ask) / 2.0,
                "spread": ask - bid,
                "raw": price
            }

        except Exception as exc:
            if isinstance(exc, BrokerAdapterError):
                raise

            raise BrokerAdapterError(
                f"Unable to retrieve symbol price: {exc}"
            ) from exc

    async def modify_position(
        self,
        account_id,
        position_id,
        stop_loss=None,
        take_profit=None
    ):
        connection = self._connection(account_id)

        if position_id is None:
            raise ValueError("position_id is required")

        if stop_loss is None and take_profit is None:
            raise ValueError(
                "At least one of stop_loss or take_profit is required"
            )

        kwargs = {}

        if stop_loss is not None:
            kwargs["stop_loss"] = float(stop_loss)

        if take_profit is not None:
            kwargs["take_profit"] = float(take_profit)

        try:
            result = await self._resolve(
                connection.modify_position(
                    str(position_id),
                    **kwargs
                )
            )

            return {
                "success": True,
                "position_id": str(position_id),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "broker_result": result
            }

        except Exception as exc:
            raise BrokerAdapterError(
                f"Unable to modify position {position_id}: {exc}"
            ) from exc

    async def close_position(self, account_id, position_id):
        connection = self._connection(account_id)

        if position_id is None:
            raise ValueError("position_id is required")

        try:
            result = await self._resolve(
                connection.close_position(str(position_id))
            )

            return {
                "success": True,
                "position_id": str(position_id),
                "broker_result": result
            }

        except Exception as exc:
            raise BrokerAdapterError(
                f"Unable to close position {position_id}: {exc}"
            ) from exc

    async def partially_close_position(
        self,
        account_id,
        position_id,
        volume
    ):
        connection = self._connection(account_id)

        if position_id is None:
            raise ValueError("position_id is required")

        volume = float(volume)

        if volume <= 0:
            raise ValueError("Partial-close volume must be positive")

        try:
            result = await self._resolve(
                connection.close_position_partially(
                    str(position_id),
                    volume
                )
            )

            return {
                "success": True,
                "position_id": str(position_id),
                "closed_volume": volume,
                "broker_result": result
            }

        except Exception as exc:
            raise BrokerAdapterError(
                f"Unable to partially close position {position_id}: {exc}"
            ) from exc

    async def open_market_position(
        self,
        account_id,
        symbol,
        direction,
        volume,
        stop_loss=None,
        take_profit=None,
        options=None
    ):
        connection = self._connection(account_id)

        if not symbol:
            raise ValueError("symbol is required")

        direction = str(direction).upper()
        volume = float(volume)

        if direction not in ("BUY", "SELL"):
            raise ValueError("direction must be BUY or SELL")

        if volume <= 0:
            raise ValueError("volume must be positive")

        kwargs = {}

        if stop_loss is not None:
            kwargs["stop_loss"] = float(stop_loss)

        if take_profit is not None:
            kwargs["take_profit"] = float(take_profit)

        if options is not None:
            kwargs["options"] = options

        try:
            if direction == "BUY":
                result = await self._resolve(
                    connection.create_market_buy_order(
                        symbol,
                        volume,
                        **kwargs
                    )
                )
            else:
                result = await self._resolve(
                    connection.create_market_sell_order(
                        symbol,
                        volume,
                        **kwargs
                    )
                )

            return {
                "success": True,
                "symbol": symbol,
                "direction": direction,
                "volume": volume,
                "broker_result": result
            }

        except Exception as exc:
            raise BrokerAdapterError(
                f"Unable to open {direction} market position: {exc}"
            ) from exc

    async def get_broker_snapshot(self, account_id):
        """
        Retrieve both positions and account information.

        If either request fails, this method raises an error.
        It never reports a failed snapshot as an empty account.
        """
        positions, information = await asyncio.gather(
            self.get_positions(account_id),
            self.get_account_information(account_id)
        )

        return {
            "account_id": str(account_id),
            "positions": positions,
            "account_information": information,
            "snapshot_valid": True
        }

    async def execute_action(self, account_id, action):
        """
        Common action interface for the live controller
        and account risk supervisor.
        """
        if not isinstance(action, dict):
            raise ValueError("action must be a dictionary")

        action_type = str(
            action.get("type", action.get("action", ""))
        ).lower()

        position_id = action.get("position_id")

        if action_type in ("modify", "modify_position"):
            return await self.modify_position(
                account_id=account_id,
                position_id=position_id,
                stop_loss=action.get("stop_loss"),
                take_profit=action.get("take_profit")
            )

        if action_type in ("close", "close_position"):
            return await self.close_position(
                account_id,
                position_id
            )

        if action_type in (
            "partial_close",
            "partially_close_position"
        ):
            return await self.partially_close_position(
                account_id,
                position_id,
                action.get("volume")
            )

        if action_type in ("open_buy", "buy"):
            return await self.open_market_position(
                account_id,
                action["symbol"],
                "BUY",
                action["volume"],
                action.get("stop_loss"),
                action.get("take_profit"),
                action.get("options")
            )

        if action_type in ("open_sell", "sell"):
            return await self.open_market_position(
                account_id,
                action["symbol"],
                "SELL",
                action["volume"],
                action.get("stop_loss"),
                action.get("take_profit"),
                action.get("options")
            )

        raise ValueError(
            f"Unsupported broker action: {action_type}"
        )
