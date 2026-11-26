
"""
GOLD SCALPER AI
File: trading/broker_adapter.py

Direct Python-to-MT5 bridge adapter.

Architecture:
    Python trading controller
          |
          v
    MT5BridgeClient
          |
          v
    Oracle MT5 Bridge Server
          |
          v
    GoldMasterEA.mq5
          |
          v
    Broker / MT5 terminal

No MetaApi.
No external paid trading connector.

IMPORTANT:
    A command timeout is an UNKNOWN execution state.
    Never automatically resend an order after a timeout.
    Reconcile the broker's actual positions first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from dataclasses import dataclass
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


logger = logging.getLogger("gold_scalper.broker_adapter")


# ============================================================
# EXCEPTIONS
# ============================================================

class BrokerAdapterError(Exception):
    """Base exception for broker adapter failures."""


class BrokerAuthenticationError(BrokerAdapterError):
    """The Oracle bridge rejected authentication."""


class BrokerConnectionError(BrokerAdapterError):
    """The Oracle bridge could not be reached."""


class BrokerRequestError(BrokerAdapterError):
    """The Oracle bridge returned an unsuccessful response."""


class BrokerCommandTimeout(BrokerAdapterError):
    """
    A command did not reach a verified terminal state in time.

    The caller MUST reconcile broker state before considering
    another order submission.
    """


class BrokerStateUnavailable(BrokerAdapterError):
    """No usable broker snapshot is currently available."""


# ============================================================
# ACCOUNT CONNECTION CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class BridgeAccountConfig:
    account_id: str
    bridge_url: str
    api_key: str
    timeout: float = 10.0

    def __post_init__(self):
        if not self.account_id or not self.account_id.strip():
            raise ValueError("account_id is required")

        if not self.bridge_url or not self.bridge_url.strip():
            raise ValueError("bridge_url is required")

        if not self.api_key or not self.api_key.strip():
            raise ValueError("api_key is required")

        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


# ============================================================
# HTTP CLIENT
# ============================================================

class MT5BridgeClient:
    """
    Authenticated HTTP client for one MT5 account.

    One client instance belongs to one account. Do not share
    account credentials or account state between customers.
    """

    def __init__(
        self,
        account_id: str,
        bridge_url: str,
        api_key: str,
        timeout: float = 10.0,
    ):
        self.config = BridgeAccountConfig(
            account_id=account_id,
            bridge_url=bridge_url.rstrip("/"),
            api_key=api_key,
            timeout=timeout,
        )

        self.account_id = account_id
        self._closed = False

    # --------------------------------------------------------
    # INTERNAL HTTP REQUEST
    # --------------------------------------------------------

    def _request_sync(
        self,
        method: str,
        endpoint: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:

        if self._closed:
            raise BrokerConnectionError(
                "Bridge client has been closed"
            )

        url = (
            self.config.bridge_url
            + "/"
            + endpoint.lstrip("/")
        )

        headers = {
            "Authorization": (
                "Bearer " + self.config.api_key
            ),
            "Accept": "application/json",
            "Cache-Control": "no-store",
        }

        data = None

        if payload is not None:
            headers["Content-Type"] = "application/json"

            data = json.dumps(
                payload,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")

        request = Request(
            url=url,
            data=data,
            headers=headers,
            method=method.upper(),
        )

        try:
            with urlopen(
                request,
                timeout=self.config.timeout,
            ) as response:

                raw = response.read()

                if not raw:
                    return {}

                try:
                    result = json.loads(
                        raw.decode("utf-8")
                    )
                except json.JSONDecodeError as exc:
                    raise BrokerRequestError(
                        "Bridge returned invalid JSON"
                    ) from exc

                if not isinstance(result, dict):
                    raise BrokerRequestError(
                        "Bridge response must be a JSON object"
                    )

                return result

        except HTTPError as exc:

            response_text = ""

            try:
                response_text = exc.read().decode(
                    "utf-8",
                    errors="replace",
                )
            except Exception:
                pass

            if exc.code == 401:
                raise BrokerAuthenticationError(
                    "Oracle bridge authentication failed"
                ) from exc

            if exc.code in (502, 503, 504):
                raise BrokerStateUnavailable(
                    f"Bridge temporarily unavailable: {response_text}"
                ) from exc

            raise BrokerRequestError(
                f"Bridge HTTP {exc.code}: {response_text}"
            ) from exc

        except (URLError, TimeoutError, OSError) as exc:

            raise BrokerConnectionError(
                f"Could not connect to Oracle MT5 bridge: {exc}"
            ) from exc

    async def request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:

        return await asyncio.to_thread(
            self._request_sync,
            method,
            endpoint,
            payload,
        )

    # --------------------------------------------------------
    # ACCOUNT QUERY HELPERS
    # --------------------------------------------------------

    def _account_endpoint(self, endpoint: str) -> str:
        separator = "&" if "?" in endpoint else "?"

        return (
            endpoint
            + separator
            + urlencode({
                "account_id": self.account_id
            })
        )

    # --------------------------------------------------------
    # HEALTH
    # --------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:

        result = await self.request(
            "GET",
            "/health",
        )

        if result.get("status") != "ok":
            raise BrokerRequestError(
                "Oracle bridge health check failed"
            )

        return result

    # --------------------------------------------------------
    # ACCOUNT INFORMATION
    # --------------------------------------------------------

    async def get_account_information(self) -> dict[str, Any]:

        endpoint = self._account_endpoint("/account")

        result = await self.request(
            "GET",
            endpoint,
        )

        if not result.get("success"):
            raise BrokerStateUnavailable(
                "Account information is unavailable"
            )

        account = result.get("account")

        if not isinstance(account, dict):
            raise BrokerStateUnavailable(
                "Invalid account snapshot"
            )

        return account

    # --------------------------------------------------------
    # OPEN POSITIONS
    # --------------------------------------------------------

    async def get_positions(self) -> list[dict[str, Any]]:

        endpoint = self._account_endpoint("/positions")

        result = await self.request(
            "GET",
            endpoint,
        )

        if not result.get("success"):
            raise BrokerStateUnavailable(
                "Position snapshot is unavailable"
            )

        positions = result.get("positions")

        if not isinstance(positions, list):
            raise BrokerStateUnavailable(
                "Invalid position snapshot"
            )

        for position in positions:
            if not isinstance(position, dict):
                raise BrokerStateUnavailable(
                    "Position snapshot contains an invalid entry"
                )

        return positions

    # --------------------------------------------------------
    # SYMBOL PRICE
    # --------------------------------------------------------

    async def get_symbol_price(
        self,
        symbol: str,
    ) -> dict[str, Any]:

        if not symbol:
            raise ValueError("symbol is required")

        endpoint = "/price?" + urlencode({
            "account_id": self.account_id,
            "symbol": symbol,
        })

        result = await self.request(
            "GET",
            endpoint,
        )

        if not result.get("success"):
            raise BrokerStateUnavailable(
                f"Price unavailable for {symbol}"
            )

        price = result.get("price")

        if not isinstance(price, dict):
            raise BrokerStateUnavailable(
                "Invalid price snapshot"
            )

        bid = price.get("bid")
        ask = price.get("ask")

        if bid is None or ask is None:
            raise BrokerStateUnavailable(
                "Price snapshot must contain bid and ask"
            )

        try:
            bid = float(bid)
            ask = float(ask)
        except (TypeError, ValueError) as exc:
            raise BrokerStateUnavailable(
                "Invalid bid/ask values"
            ) from exc

        if bid <= 0 or ask <= 0 or ask < bid:
            raise BrokerStateUnavailable(
                "Broker returned invalid bid/ask prices"
            )

        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "last": price.get("last"),
            "time_msc": price.get("time_msc"),
            "updated_at": result.get("updated_at"),
        }

    # --------------------------------------------------------
    # FULL BROKER SNAPSHOT
    # --------------------------------------------------------

    async def get_broker_snapshot(
        self,
        symbol: Optional[str] = None,
    ) -> dict[str, Any]:

        account_task = self.get_account_information()
        positions_task = self.get_positions()

        results = await asyncio.gather(
            account_task,
            positions_task,
            return_exceptions=True,
        )

        account = results[0]
        positions = results[1]

        if isinstance(account, BaseException):
            raise account

        if isinstance(positions, BaseException):
            raise positions

        snapshot = {
            "account_id": self.account_id,
            "account": account,
            "positions": positions,
        }

        if symbol:
            snapshot["price"] = await self.get_symbol_price(
                symbol
            )

        return snapshot

    # --------------------------------------------------------
    # SUBMIT COMMAND
    # --------------------------------------------------------

    async def send_command(
        self,
        command: dict[str, Any],
    ) -> str:

        if not isinstance(command, dict):
            raise ValueError("command must be a dictionary")

        command_payload = dict(command)

        payload = {
            "account_id": self.account_id,
            "command": command_payload,
        }

        result = await self.request(
            "POST",
            "/commands",
            payload,
        )

        command_id = result.get("command_id")

        if not command_id:
            raise BrokerRequestError(
                "Bridge did not return a command ID"
            )

        return str(command_id)

    # --------------------------------------------------------
    # COMMAND RESULT
    # --------------------------------------------------------

    async def get_command_result(
        self,
        command_id: str,
    ) -> dict[str, Any]:

        if not command_id:
            raise ValueError("command_id is required")

        result = await self.request(
            "GET",
            "/commands/" + command_id,
        )

        if result.get("account_id") != self.account_id:
            raise BrokerRequestError(
                "Command account does not match this client"
            )

        return result

    # --------------------------------------------------------
    # WAIT FOR COMMAND
    # --------------------------------------------------------

    async def execute_and_wait(
        self,
        command: dict[str, Any],
        timeout: float = 30.0,
        poll_interval: float = 0.25,
    ) -> dict[str, Any]:

        if timeout <= 0:
            raise ValueError("timeout must be positive")

        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")

        command_id = await self.send_command(command)

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:

            result = await self.get_command_result(
                command_id
            )

            status = result.get("status")

            if status == "complete":

                return {
                    "success": True,
                    "command_id": command_id,
                    "status": status,
                    "result": result.get("result"),
                }

            if status in (
                "failed",
                "rejected",
                "cancelled",
            ):

                return {
                    "success": False,
                    "command_id": command_id,
                    "status": status,
                    "error": result.get("error"),
                    "result": result.get("result"),
                }

            await asyncio.sleep(poll_interval)

        raise BrokerCommandTimeout(
            "Command did not reach a verified terminal state. "
            f"Command ID: {command_id}. "
            "Reconcile broker positions before retrying."
        )

    # --------------------------------------------------------
    # ORDER OPENING
    # --------------------------------------------------------

    async def open_market_position(
        self,
        symbol: str,
        direction: str,
        volume: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        position_number: Optional[int] = None,
        comment: Optional[str] = None,
    ) -> dict[str, Any]:

        direction = direction.upper()

        if direction not in ("BUY", "SELL"):
            raise ValueError(
                "direction must be BUY or SELL"
            )

        if not symbol:
            raise ValueError("symbol is required")

        if volume <= 0:
            raise ValueError("volume must be positive")

        command = {
            "action": "open_market_position",
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position_number": position_number,
            "comment": comment,
        }

        return await self.execute_and_wait(command)

    # --------------------------------------------------------
    # MODIFY POSITION
    # --------------------------------------------------------

    async def modify_position(
        self,
        position_id: int | str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> dict[str, Any]:

        if not position_id:
            raise ValueError("position_id is required")

        command = {
            "action": "modify_position",
            "position_id": str(position_id),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }

        return await self.execute_and_wait(command)

    # --------------------------------------------------------
    # CLOSE POSITION
    # --------------------------------------------------------

    async def close_position(
        self,
        position_id: int | str,
    ) -> dict[str, Any]:

        if not position_id:
            raise ValueError("position_id is required")

        command = {
            "action": "close_position",
            "position_id": str(position_id),
        }

        return await self.execute_and_wait(command)

    # --------------------------------------------------------
    # PARTIAL CLOSE
    # --------------------------------------------------------

    async def partially_close_position(
        self,
        position_id: int | str,
        volume: float,
    ) -> dict[str, Any]:

        if not position_id:
            raise ValueError("position_id is required")

        if volume <= 0:
            raise ValueError("volume must be positive")

        command = {
            "action": "partial_close",
            "position_id": str(position_id),
            "volume": volume,
        }

        return await self.execute_and_wait(command)

    # --------------------------------------------------------
    # GENERIC ACTION ROUTER
    # --------------------------------------------------------

    async def execute_action(
        self,
        action: dict[str, Any],
    ) -> dict[str, Any]:

        if not isinstance(action, dict):
            raise ValueError("action must be a dictionary")

        action_type = (
            action.get("action")
            or action.get("type")
        )

        if action_type == "open_market_position":
            return await self.open_market_position(
                symbol=action["symbol"],
                direction=action["direction"],
                volume=float(action["volume"]),
                stop_loss=action.get("stop_loss"),
                take_profit=action.get("take_profit"),
                position_number=action.get("position_number"),
                comment=action.get("comment"),
            )

        if action_type == "modify_position":
            return await self.modify_position(
                position_id=action["position_id"],
                stop_loss=action.get("stop_loss"),
                take_profit=action.get("take_profit"),
            )

        if action_type == "close_position":
            return await self.close_position(
                position_id=action["position_id"],
            )

        if action_type == "partial_close":
            return await self.partially_close_position(
                position_id=action["position_id"],
                volume=float(action["volume"]),
            )

        raise ValueError(
            f"Unsupported broker action: {action_type}"
        )

    # --------------------------------------------------------
    # CLIENT SHUTDOWN
    # --------------------------------------------------------

    async def close(self):
        self._closed = True


# ============================================================
# MULTI-ACCOUNT ADAPTER REGISTRY
# ============================================================

class MetaTraderBrokerAdapter:
    """
    Maintains isolated bridge clients for multiple MT5 accounts.

    The class name is retained for compatibility with earlier
    controller imports. It does not use MetaApi.
    """

    def __init__(self):
        self._clients: dict[str, MT5BridgeClient] = {}
        self._registry_lock = asyncio.Lock()

    async def register_account(
        self,
        account_id: str,
        bridge_url: str,
        api_key: str,
        timeout: float = 10.0,
    ) -> MT5BridgeClient:

        if not account_id:
            raise ValueError("account_id is required")

        async with self._registry_lock:

            existing = self._clients.get(account_id)

            if existing is not None:
                await existing.close()

            client = MT5BridgeClient(
                account_id=account_id,
                bridge_url=bridge_url,
                api_key=api_key,
                timeout=timeout,
            )

            self._clients[account_id] = client

            return client

    async def get_account_client(
        self,
        account_id: str,
    ) -> MT5BridgeClient:

        client = self._clients.get(account_id)

        if client is None:
            raise BrokerConnectionError(
                f"No MT5 bridge registered for account {account_id}"
            )

        return client

    async def remove_account(
        self,
        account_id: str,
    ):

        async with self._registry_lock:

            client = self._clients.pop(
                account_id,
                None
            )

            if client is not None:
                await client.close()

    async def health_check(
        self,
        account_id: str,
    ):

        client = await self.get_account_client(
            account_id
        )

        return await client.health_check()

    async def get_positions(
        self,
        account_id: str,
    ):

        client = await self.get_account_client(
            account_id
        )

        return await client.get_positions()

    async def get_account_information(
        self,
        account_id: str,
    ):

        client = await self.get_account_client(
            account_id
        )

        return await client.get_account_information()

    async def get_symbol_price(
        self,
        account_id: str,
        symbol: str,
    ):

        client = await self.get_account_client(
            account_id
        )

        return await client.get_symbol_price(
            symbol
        )

    async def get_broker_snapshot(
        self,
        account_id: str,
        symbol: Optional[str] = None,
    ):

        client = await self.get_account_client(
            account_id
        )

        return await client.get_broker_snapshot(
            symbol
        )

    async def execute_action(
        self,
        account_id: str,
        action: dict[str, Any],
    ):

        client = await self.get_account_client(
            account_id
        )

        return await client.execute_action(
            action
        )

    async def close(self):

        async with self._registry_lock:

            clients = list(
                self._clients.values()
            )

            self._clients.clear()

        await asyncio.gather(
            *[
                client.close()
                for client in clients
            ],
            return_exceptions=True,
        )


# Compatibility alias for existing imports.
BrokerAdapter = MetaTraderBrokerAdapter
