import time
from dataclasses import dataclass
from typing import Any

import MetaTrader5 as mt5


@dataclass
class MT5ConnectionResult:
    connected: bool
    message: str
    account_info: dict[str, Any] | None = None


class MT5Client:
    """
    Connects to one isolated Windows MT5 terminal.

    Preserves the original Gold Scalper execution style:
    - XAUUSD symbol resolution
    - Market BUY and SELL execution
    - SL/TP submission
    - Position closing
    - Bot signature comments
    """

    SYMBOL_CANDIDATES = [
        "XAUUSDm",
        "XAUUSD",
        "XAUUSDc",
        "XAUUSDr",
        "GOLD",
    ]

    def __init__(self):
        self.initialized = False
        self.connected = False
        self.active_symbol: str | None = None

    def initialize(self) -> MT5ConnectionResult:
        if not mt5.initialize():
            return MT5ConnectionResult(
                connected=False,
                message=(
                    f"MT5 initialization failed: "
                    f"{mt5.last_error()}"
                ),
            )

        self.initialized = True

        return MT5ConnectionResult(
            connected=True,
            message="MT5 terminal initialized.",
        )

    def login(
        self,
        login: str,
        password: str,
        server: str,
    ) -> MT5ConnectionResult:
        if not self.initialized:
            init_result = self.initialize()

            if not init_result.connected:
                return init_result

        login_value = int(str(login).strip())

        connected = mt5.login(
            login=login_value,
            password=password,
            server=server,
        )

        if not connected:
            return MT5ConnectionResult(
                connected=False,
                message=(
                    f"MT5 login failed for account {login}: "
                    f"{mt5.last_error()}"
                ),
            )

        account_info = mt5.account_info()

        if account_info is None:
            return MT5ConnectionResult(
                connected=False,
                message="MT5 account information is unavailable.",
            )

        self.connected = True

        return MT5ConnectionResult(
            connected=True,
            message="MT5 account connected.",
            account_info={
                "login": account_info.login,
                "server": account_info.server,
                "balance": account_info.balance,
                "equity": account_info.equity,
                "free_margin": account_info.margin_free,
                "margin_level": account_info.margin_level,
            },
        )

    def resolve_gold_symbol(
        self,
        requested_symbol: str,
    ) -> str:
        candidates = [requested_symbol]

        for candidate in self.SYMBOL_CANDIDATES:
            if candidate not in candidates:
                candidates.append(candidate)

        for symbol in candidates:
            if not symbol:
                continue

            symbol_info = mt5.symbol_info(symbol)

            if symbol_info is None:
                continue

            if not symbol_info.visible:
                mt5.symbol_select(symbol, True)

            tick = mt5.symbol_info_tick(symbol)

            if tick and (tick.bid > 0 or tick.ask > 0):
                self.active_symbol = symbol

                return symbol

        self.active_symbol = requested_symbol

        return requested_symbol

    def get_symbol_tick(self, symbol: str) -> dict[str, float] | None:
        tick = mt5.symbol_info_tick(symbol)

        if not tick:
            return None

        if tick.bid <= 0 or tick.ask <= 0:
            return None

        return {
            "bid": float(tick.bid),
            "ask": float(tick.ask),
        }

    def get_account_state(self) -> dict[str, Any] | None:
        account_info = mt5.account_info()

        if not account_info:
            return None

        return {
            "login": account_info.login,
            "balance": float(account_info.balance),
            "equity": float(account_info.equity),
            "free_margin": float(account_info.margin_free),
            "margin_level": float(account_info.margin_level),
        }

    def get_open_positions(self, symbol: str) -> list[dict[str, Any]]:
        positions = mt5.positions_get(symbol=symbol)

        if not positions:
            return []

        result = []

        for position in positions:
            result.append(
                {
                    "ticket": position.ticket,
                    "symbol": position.symbol,
                    "type": (
                        "BUY"
                        if position.type == mt5.POSITION_TYPE_BUY
                        else "SELL"
                    ),
                    "volume": float(position.volume),
                    "price_open": float(position.price_open),
                    "profit": float(position.profit),
                    "comment": position.comment,
                }
            )

        return result

    def open_market_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        stop_loss: float,
        take_profit: float,
        comment: str,
    ) -> dict[str, Any]:
        if direction not in ["BUY", "SELL"]:
            return {
                "success": False,
                "message": "Direction must be BUY or SELL.",
            }

        order_type = (
            mt5.ORDER_TYPE_BUY
            if direction == "BUY"
            else mt5.ORDER_TYPE_SELL
        )

        tick = self.get_symbol_tick(symbol)

        if not tick:
            return {
                "success": False,
                "message": "No valid market price available.",
            }

        price = (
            tick["ask"]
            if direction == "BUY"
            else tick["bid"]
        )

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": float(price),
            "sl": float(stop_loss),
            "tp": float(take_profit),
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result is None:
            return {
                "success": False,
                "message": f"MT5 order send failed: {mt5.last_error()}",
            }

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "message": (
                    f"MT5 order rejected. "
                    f"Retcode: {result.retcode}. "
                    f"Comment: {result.comment}"
                ),
                "result": result._asdict(),
            }

        return {
            "success": True,
            "message": (
                f"{direction} order opened on {symbol} "
                f"with {volume} lots."
            ),
            "order_ticket": result.order,
            "deal_ticket": result.deal,
            "price": result.price,
        }

    def close_position(self, ticket: int) -> dict[str, Any]:
        positions = mt5.positions_get(ticket=ticket)

        if not positions:
            return {
                "success": False,
                "message": f"Position {ticket} not found.",
            }

        position = positions[0]

        tick = self.get_symbol_tick(position.symbol)

        if not tick:
            return {
                "success": False,
                "message": "No valid market price available.",
            }

        if position.type == mt5.POSITION_TYPE_BUY:
            direction = "SELL"
            price = tick["bid"]
            order_type = mt5.ORDER_TYPE_SELL

        else:
            direction = "BUY"
            price = tick["ask"]
            order_type = mt5.ORDER_TYPE_BUY

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": float(position.volume),
            "type": order_type,
            "position": int(position.ticket),
            "price": float(price),
            "comment": "BALANCED-SCALP-CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result is None:
            return {
                "success": False,
                "message": f"MT5 close failed: {mt5.last_error()}",
            }

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "message": (
                    f"MT5 close rejected. "
                    f"Retcode: {result.retcode}. "
                    f"Comment: {result.comment}"
                ),
                "result": result._asdict(),
            }

        return {
            "success": True,
            "message": (
                f"Position {ticket} closed with {direction} order."
            ),
            "order_ticket": result.order,
            "deal_ticket": result.deal,
        }

    def close_all_positions(self, symbol: str) -> dict[str, Any]:
        positions = self.get_open_positions(symbol)

        if not positions:
            return {
                "success": True,
                "message": "No open positions to close.",
                "closed_count": 0,
            }

        closed_count = 0
        errors = []

        for position in positions:
            close_result = self.close_position(position["ticket"])

            if close_result["success"]:
                closed_count += 1

            else:
                errors.append(close_result["message"])

        return {
            "success": closed_count == len(positions),
            "message": (
                f"Closed {closed_count}/{len(positions)} positions."
            ),
            "closed_count": closed_count,
            "errors": errors,
        }

    def shutdown(self) -> None:
        if self.initialized:
            mt5.shutdown()

        self.initialized = False
        self.connected = False
        self.active_symbol = None
