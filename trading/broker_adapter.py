
"""
Oracle Cloud MT5 Broker Adapter.

This module communicates with an MT5 Expert Advisor through
a local HTTP bridge.

Architecture:
    Python trading controller
        |
        | HTTP/JSON
        v
    Local MT5 bridge
        |
        | EA polling and acknowledgements
        v
    MT5 Expert Advisor
        |
        v
    MT5 terminal / broker

No MetaApi connection is used here.

The matching bridge server and MQL5 EA must implement the
same HTTP protocol before this adapter can execute trades.
"""

import asyncio
import json
import time
import urllib.error
import urllib.request

from typing import Any, Dict, Optional
from urllib.parse import quote


class BrokerAdapterError(RuntimeError):
    """Raised when the MT5 bridge operation fails."""


class MT5BridgeClient:
    """
    HTTP client for one Oracle-hosted MT5 bridge.

    Each trading account receives its own bridge configuration.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = 10.0
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = float(timeout)

        if not self.base_url.startswith("http://") and not (
            self.base_url.startswith("https://")
        ):
            raise ValueError("Bridge URL must use HTTP or HTTPS")

        if self.timeout <= 0:
            raise ValueError("Timeout must be positive")

    def _request_sync(
        self,
        method: str,
        path: str,
        payload: Optional[dict] = None
    ):
        url = self.base_url + path

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        if self.api_key:
            headers["Authorization"] = (
                f"Bearer {self.api_key}"
            )

        body = None

        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            url=url,
            data=body,
            headers=headers,
            method=method.upper()
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout
            ) as response:
                raw = response.read().decode("utf-8")

                if not raw:
                    return {}

                result = json.loads(raw)

                if not isinstance(result, dict):
                    raise BrokerAdapterError(
                        "Bridge returned an invalid response"
                    )

                if result.get("success") is False:
                    raise BrokerAdapterError(
                        result.get(
                            "error",
                            "Bridge operation failed"
                        )
                    )

                return result

        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(
                "utf-8",
                errors="replace"
            )

            raise BrokerAdapterError(
                f"Bridge HTTP error {exc.code}: {detail}"
            ) from exc

        except urllib.error.URLError as exc:
            raise BrokerAdapterError(
                f"Cannot reach MT5 bridge: {exc}"
            ) from exc

        except TimeoutError as exc:
            raise BrokerAdapterError(
                "MT5 bridge request timed out"
            ) from exc

        except json.JSONDecodeError as exc:
            raise BrokerAdapterError(
                "MT5 bridge returned invalid JSON"
            ) from exc

    async def request(
        self,
        method: str,
        path: str,
        payload: Optional[dict] = None
    ):
        return await asyncio.to_thread(
            self._request_sync,
            method,
            path,
            payload
        )


class MetaTraderBrokerAdapter:
    """
    Account-isolated interface between the trading controller
    and Oracle-hosted MT5 Expert Advisors.

    This adapter transports commands and reads EA-reported
    broker state. It does not independently execute orders.
    """

    def __init__(self):
        self.bridges: Dict[str, MT5BridgeClient] = {}
        self.account_metadata: Dict[str, dict] = {}

    def register_account(
        self,
        account_id: str,
        bridge_url: str,
        symbol: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 10.0
    ):
        account_id = str(account_id)

        if not account_id:
            raise ValueError("account_id is required")

        self.bridges[account_id] = MT5BridgeClient(
            base_url=bridge_url,
            api_key=api_key,
            timeout=timeout
        )

        self.account_metadata[account_id] = {
            "symbol": symbol
        }

    def unregister_account(self, account_id: str):
        account_id = str(account_id)

        self.bridges.pop(account_id, None)
        self.account_metadata.pop(account_id, None)

    def _bridge(self, account_id):
        account_id = str(account_id)

        bridge = self.bridges.get(account_id)

        if bridge is None:
            raise BrokerAdapterError(
                f"No Oracle MT5 bridge registered for {account_id}"
            )

        return bridge

    async def health_check(self, account_id):
        bridge = self._bridge(account_id)

        result = await bridge.request(
            "GET",
            "/health"
        )

        if result.get("status") not in ("ok", "healthy"):
            raise BrokerAdapterError(
                "MT5 bridge is not reporting a healthy state"
            )

        return result

    async def get_positions(self, account_id):
        bridge = self._bridge(account_id)

        result = await bridge.request(
            "GET",
            "/positions"
        )

        positions = result.get("positions")

        if not isinstance(positions, list):
            raise BrokerAdapterError(
                "Bridge returned an invalid positions snapshot"
            )

        return positions

    async def get_account_information(self, account_id):
        bridge = self._bridge(account_id)

        result = await bridge.request(
            "GET",
            "/account"
        )

        information = result.get("account_information")

        if not isinstance(information, dict):
            raise BrokerAdapterError(
                "Bridge returned invalid account information"
            )

        return information

    async def get_symbol_price(
        self,
        account_id,
        symbol=None
    ):
        bridge = self._bridge(account_id)

        if not symbol:
            symbol = self.account_metadata.get(
                str(account_id), {}
            ).get("symbol")

        if not symbol:
            raise ValueError("Trading symbol is required")

        result = await bridge.request(
            "GET",
            "/price?symbol=" + quote(str(symbol), safe="")
        )

        price = result.get("price")

        if not isinstance(price, dict):
            raise BrokerAdapterError(
                "Bridge returned invalid price information"
            )

        bid = float(price["bid"])
        ask = float(price["ask"])

        if bid <= 0 or ask <= 0 or ask < bid:
            raise BrokerAdapterError(
                "Invalid MT5 bid/ask prices"
            )

        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "mid": (bid + ask) / 2.0,
            "spread": ask - bid
        }

    async def send_command(self, account_id, command):
        bridge = self._bridge(account_id)

        if not isinstance(command, dict):
            raise ValueError("Command must be a dictionary")

        command_type = command.get("type")

        if not command_type:
            raise ValueError("Command type is required")

        payload = {
            "account_id": str(account_id),
            "command": command,
            "created_at": time.time()
        }

        result = await bridge.request(
            "POST",
            "/commands",
            payload
        )

        command_id = result.get("command_id")

        if not command_id:
            raise BrokerAdapterError(
                "Bridge did not return a command ID"
            )

        return {
            "success": True,
            "command_id": str(command_id),
            "status": result.get("status", "queued")
        }

    async def get_command_result(
        self,
        account_id,
        command_id
    ):
        bridge = self._bridge(account_id)

        result = await bridge.request(
            "GET",
            "/commands/" + quote(
                str(command_id),
                safe=""
            )
        )

        return result

    async def execute_and_wait(
        self,
        account_id,
        command,
        timeout_seconds=30.0,
        poll_interval=0.25
    ):
        """
        Submit a command and wait for the EA's execution result.

        A queued command is not considered a successful trade.
        Only a completed EA response is accepted.
        """
        submitted = await self.send_command(
            account_id,
            command
        )

        command_id = submitted["command_id"]
        deadline = time.monotonic() + float(timeout_seconds)

        while time.monotonic() < deadline:
            result = await self.get_command_result(
                account_id,
                command_id
            )

            status = str(
                result.get("status", "")
            ).lower()

            if status in ("completed", "executed", "success"):
                if result.get("success") is False:
                    raise BrokerAdapterError(
                        result.get(
                            "error",
                            "MT5 execution failed"
                        )
                    )

                return result

            if status in ("failed", "rejected", "cancelled"):
                raise BrokerAdapterError(
                    result.get(
                        "error",
                        "MT5 command was not executed"
                    )
                )

            await asyncio.sleep(poll_interval)

        raise BrokerAdapterError(
            f"Timed out waiting for MT5 command {command_id}; "
            "execution state must be reconciled before retrying"
        )

    async def modify_position(
        self,
        account_id,
        position_id,
        stop_loss=None,
        take_profit=None
    ):
        if stop_loss is None and take_profit is None:
            raise ValueError(
                "SL or TP must be supplied"
            )

        command = {
            "type": "modify_position",
            "position_id": str(position_id),
            "stop_loss": stop_loss,
            "take_profit": take_profit
        }

        return await self.execute_and_wait(
            account_id,
            command
        )

    async def close_position(self, account_id, position_id):
        command = {
            "type": "close_position",
            "position_id": str(position_id)
        }

        return await self.execute_and_wait(
            account_id,
            command
        )

    async def partially_close_position(
        self,
        account_id,
        position_id,
        volume
    ):
        volume = float(volume)

        if volume <= 0:
            raise ValueError(
                "Partial close volume must be positive"
            )

        command = {
            "type": "partial_close",
            "position_id": str(position_id),
            "volume": volume
        }

        return await self.execute_and_wait(
            account_id,
            command
        )

    async def open_market_position(
        self,
        account_id,
        symbol,
        direction,
        volume,
        stop_loss=None,
        take_profit=None
    ):
        direction = str(direction).upper()
        volume = float(volume)

        if direction not in ("BUY", "SELL"):
            raise ValueError(
                "Direction must be BUY or SELL"
            )

        if volume <= 0:
            raise ValueError(
                "Volume must be positive"
            )

        command = {
            "type": "open_market_position",
            "symbol": str(symbol),
            "direction": direction,
            "volume": volume,
            "stop_loss": stop_loss,
            "take_profit": take_profit
        }

        return await self.execute_and_wait(
            account_id,
            command
        )

    async def execute_action(self, account_id, action):
        if not isinstance(action, dict):
            raise ValueError("Action must be a dictionary")

        action_type = str(
            action.get("type", action.get("action", ""))
        ).lower()

        position_id = action.get("position_id")

        if action_type in ("modify", "modify_position"):
            return await self.modify_position(
                account_id,
                position_id,
                action.get("stop_loss"),
                action.get("take_profit")
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

        if action_type in ("buy", "open_buy"):
            return await self.open_market_position(
                account_id,
                action["symbol"],
                "BUY",
                action["volume"],
                action.get("stop_loss"),
                action.get("take_profit")
            )

        if action_type in ("sell", "open_sell"):
            return await self.open_market_position(
                account_id,
                action["symbol"],
                "SELL",
                action["volume"],
                action.get("stop_loss"),
                action.get("take_profit")
            )

        raise ValueError(
            f"Unsupported MT5 action: {action_type}"
        )

    async def get_broker_snapshot(self, account_id):
        """
        Retrieve both positions and account information.

        A failed request is not treated as an empty account.
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


# Compatibility alias for modules using the earlier class name.
BrokerAdapter = MetaTraderBrokerAdapter
