import logging
from typing import Any, Dict, List, Optional

import MetaTrader5 as mt5

from worker.config import (
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_SERVER,
    MT5_TERMINAL_PATH
)

logger = logging.getLogger(__name__)


class MT5Client:
    def __init__(self):
        self.initialized = False
        self.logged_in = False

    def initialize(self) -> bool:
        if self.initialized:
            return True

        initialize_kwargs = {}

        if MT5_TERMINAL_PATH:
            initialize_kwargs["path"] = MT5_TERMINAL_PATH

        if not mt5.initialize(**initialize_kwargs):
            logger.error(
                "MT5 initialization failed: %s",
                mt5.last_error()
            )

            return False

        self.initialized = True

        return True

    def login(self) -> bool:
        if self.logged_in:
            return True

        if not self.initialize():
            return False

        if not mt5.login(
            login=int(MT5_LOGIN),
            password=MT5_PASSWORD,
            server=MT5_SERVER
        ):
            logger.error(
                "MT5 login failed: %s",
                mt5.last_error()
            )

            return False

        self.logged_in = True

        return True

    def shutdown(self) -> None:
        if self.initialized:
            mt5.shutdown()

            self.initialized = False
            self.logged_in = False

    def get_symbol_info(
        self,
        symbol: str
    ) -> Optional[Dict[str, Any]]:
        if not self.login():
            return None

        symbol_info = mt5.symbol_info(symbol)

        if symbol_info is None:
            logger.error(
                "Symbol not found: %s",
                symbol
            )

            return None

        if not mt5.symbol_select(symbol, True):
            logger.error(
                "Could not select symbol: %s",
                symbol
            )

            return None

        return {
            "symbol": symbol_info.name,
            "digits": symbol_info.digits,
            "point": symbol_info.point,
            "volume_min": symbol_info.volume_min,
            "volume_max": symbol_info.volume_max,
            "volume_step": symbol_info.volume_step
        }

    def get_quote(
        self,
        symbol: str
    ) -> Optional[Dict[str, Any]]:
        if not self.login():
            return None

        tick = mt5.symbol_info_tick(symbol)

        if tick is None:
            logger.error(
                "No quote available for symbol: %s",
                symbol
            )

            return None

        return {
            "symbol": symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "time": tick.time
        }

    def get_open_positions(
        self,
        symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if not self.login():
            return []

        positions = mt5.positions_get(
            symbol=symbol
        ) if symbol else mt5.positions_get()

        if positions is None:
            return []

        normalized_positions = []

        for position in positions:
            normalized_positions.append(
                {
                    "ticket": position.ticket,
                    "symbol": position.symbol,
                    "type": (
                        "BUY"
                        if position.type == mt5.POSITION_TYPE_BUY
                        else "SELL"
                    ),
                    "volume": position.volume,
                    "price_open": position.price_open,
                    "profit": position.profit,
                    "comment": position.comment
                }
            )

        return normalized_positions

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        if not self.login():
            return None

        account_info = mt5.account_info()

        if account_info is None:
            logger.error(
                "Could not get MT5 account info"
            )

            return None

        return {
            "login": account_info.login,
            "server": account_info.server,
            "currency": account_info.currency,
            "balance": account_info.balance,
            "equity": account_info.equity,
            "margin": account_info.margin,
            "free_margin": account_info.margin_free,
            "margin_level": account_info.margin_level
        }

    def open_position(
        self,
        symbol: str,
        direction: str,
        volume: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "BossMode"
    ) -> Dict[str, Any]:
        if not self.login():
            return {
                "status": "ERROR",
                "reason": "MT5 login failed"
            }

        quote = self.get_quote(symbol)

        if quote is None:
            return {
                "status": "ERROR",
                "reason": "No quote available"
            }

        if direction == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = quote["ask"]
        elif direction == "SELL":
            order_type = mt5.ORDER_TYPE_SELL
            price = quote["bid"]
        else:
            return {
                "status": "ERROR",
                "reason": "Invalid direction"
            }

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 991001,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC
        }

        if stop_loss is not None:
            request["sl"] = stop_loss

        if take_profit is not None:
            request["tp"] = take_profit

        result = mt5.order_send(request)

        if result is None:
            return {
                "status": "ERROR",
                "reason": "MT5 order_send returned None"
            }

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "status": "REJECTED",
                "reason": result.comment,
                "retcode": result.retcode
            }

        return {
            "status": "EXECUTED",
            "ticket": result.order,
            "price": result.price,
            "volume": volume,
            "comment": result.comment
        }

    def close_position(
        self,
        ticket: int,
        volume: Optional[float] = None,
        comment: str = "BossMode Close"
    ) -> Dict[str, Any]:
        if not self.login():
            return {
                "status": "ERROR",
                "reason": "MT5 login failed"
            }

        positions = mt5.positions_get(
            ticket=ticket
        )

        if not positions:
            return {
                "status": "ERROR",
                "reason": "Position not found"
            }

        position = positions[0]

        symbol = position.symbol

        quote = self.get_quote(symbol)

        if quote is None:
            return {
                "status": "ERROR",
                "reason": "No quote available"
            }

        if position.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = quote["bid"]
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = quote["ask"]

        close_volume = (
            volume
            if volume is not None
            else position.volume
        )

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": close_volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 991001,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC
        }

        result = mt5.order_send(request)

        if result is None:
            return {
                "status": "ERROR",
                "reason": "MT5 order_send returned None"
            }

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "status": "REJECTED",
                "reason": result.comment,
                "retcode": result.retcode
            }

        return {
            "status": "EXECUTED",
            "ticket": ticket,
            "closed_volume": close_volume,
            "price": result.price,
            "comment": result.comment
        }


mt5_client = MT5Client()
