
"""
Gold Scalper AI
File: trading/account_manager.py

Multi-account orchestration layer.

Responsibilities:
- Register and isolate MT5 account connections.
- Connect/disconnect accounts.
- Verify broker data before enabling trading.
- Run optional reconciliation and trading callbacks.
- Keep credentials out of status responses and logs.

This module does NOT contain entry strategy, lot sizing, or trading rules.
The original strategy engine must be injected through callbacks.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from trading.mt5_connector import MT5Connector


logger = logging.getLogger(__name__)


Callback = Callable[..., Any]


@dataclass
class AccountRuntime:
    account_id: str
    symbol: str

    bridge_url: str
    api_key: str = field(repr=False)

    timeout: float = 10.0

    registered: bool = False
    connected: bool = False
    trading_enabled: bool = False
    readiness_verified: bool = False

    last_check_time: Optional[float] = None
    last_error: Optional[str] = None

    account_snapshot: Optional[dict[str, Any]] = None
    positions_snapshot: list[dict[str, Any]] = field(default_factory=list)
    price_snapshot: Optional[dict[str, Any]] = None

    runtime_started_at: Optional[float] = None

    # Internal lock prevents simultaneous start/stop/connect operations.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class AccountManager:
    """
    Coordinates account connections and trading lifecycle.

    Callback signatures:
        reconcile_callback(account_id, snapshot)
        start_callback(account_id, snapshot)
        stop_callback(account_id)

    Callbacks may be synchronous or asynchronous.

    Important:
    This class does not create a trading loop by itself. The actual engine
    must be supplied through start_callback.
    """

    def __init__(
        self,
        connector: Optional[MT5Connector] = None,
        *,
        reconcile_callback: Optional[Callback] = None,
        start_callback: Optional[Callback] = None,
        stop_callback: Optional[Callback] = None,
    ) -> None:
        self.connector = connector or MT5Connector()

        self.reconcile_callback = reconcile_callback
        self.start_callback = start_callback
        self.stop_callback = stop_callback

        self._accounts: dict[str, AccountRuntime] = {}
        self._registry_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Callback helper
    # ------------------------------------------------------------------

    async def _invoke_callback(
        self,
        callback: Optional[Callback],
        *args: Any,
    ) -> Any:
        if callback is None:
            return None

        result = callback(*args)

        if inspect.isawaitable(result):
            return await result

        return result

    # ------------------------------------------------------------------
    # Account registration
    # ------------------------------------------------------------------

    async def register_account(
        self,
        *,
        account_id: str,
        bridge_url: str,
        api_key: str,
        symbol: str = "XAUUSD",
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """
        Register one account with the MT5 connector.

        The API key is kept in runtime memory and is never returned by
        status methods.

        Persistent credential storage should be handled by the project's
        secure credential/database layer, not by this manager.
        """

        account_id = str(account_id).strip()
        bridge_url = str(bridge_url).strip()
        symbol = str(symbol).strip()

        if not account_id:
            raise ValueError("account_id is required")

        if not bridge_url:
            raise ValueError("bridge_url is required")

        if not api_key:
            raise ValueError("api_key is required")

        if not symbol:
            raise ValueError("symbol is required")

        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        async with self._registry_lock:
            existing = self._accounts.get(account_id)

            if existing is not None:
                async with existing.lock:
                    if existing.trading_enabled:
                        raise RuntimeError(
                            "Stop trading before replacing account configuration"
                        )

                    await self.connector.disconnect_account(account_id)

            runtime = AccountRuntime(
                account_id=account_id,
                bridge_url=bridge_url,
                api_key=api_key,
                symbol=symbol,
                timeout=float(timeout),
            )

            self.connector.register_account(
                account_id=account_id,
                bridge_url=bridge_url,
                api_key=api_key,
                timeout=float(timeout),
            )

            runtime.registered = True
            self._accounts[account_id] = runtime

        return {
            "success": True,
            "account_id": account_id,
            "registered": True,
            "symbol": symbol,
        }

    # ------------------------------------------------------------------
    # Account lookup
    # ------------------------------------------------------------------

    def _get_runtime(self, account_id: str) -> AccountRuntime:
        runtime = self._accounts.get(str(account_id))

        if runtime is None:
            raise KeyError(f"Account is not registered: {account_id}")

        return runtime

    # ------------------------------------------------------------------
    # Connection and broker readiness
    # ------------------------------------------------------------------

    async def connect_account(
        self,
        account_id: str,
        *,
        verify_price: bool = True,
    ) -> dict[str, Any]:
        """
        Connect to the account and verify broker snapshots.

        The EA must be running and publishing account/position/price state
        to the bridge before readiness can be confirmed.
        """

        runtime = self._get_runtime(account_id)

        async with runtime.lock:
            runtime.last_error = None
            runtime.readiness_verified = False

            try:
                connection_result = await self.connector.connect_account(
                    runtime.account_id
                )

                if isinstance(connection_result, dict):
                    if connection_result.get("success") is False:
                        raise RuntimeError(
                            connection_result.get(
                                "error",
                                "Connector failed to connect",
                            )
                        )

                client = self.connector.get_client(runtime.account_id)

                if client is None:
                    raise RuntimeError(
                        "Connector did not provide an account client"
                    )

                snapshot = await client.get_broker_snapshot(
                    account_id=runtime.account_id,
                    symbol=runtime.symbol,
                )

                if not isinstance(snapshot, dict):
                    raise RuntimeError("Invalid broker snapshot")

                account_data = snapshot.get("account")
                positions_data = snapshot.get("positions")
                price_data = snapshot.get("price")

                if not isinstance(account_data, dict):
                    raise RuntimeError(
                        "Broker account snapshot is unavailable"
                    )

                if not isinstance(positions_data, list):
                    raise RuntimeError(
                        "Broker positions snapshot is unavailable"
                    )

                if verify_price and not isinstance(price_data, dict):
                    raise RuntimeError(
                        "Broker price snapshot is unavailable"
                    )

                runtime.account_snapshot = account_data
                runtime.positions_snapshot = positions_data
                runtime.price_snapshot = price_data

                runtime.connected = True
                runtime.readiness_verified = True
                runtime.last_check_time = time.time()

                return {
                    "success": True,
                    "account_id": runtime.account_id,
                    "connected": True,
                    "readiness_verified": True,
                    "symbol": runtime.symbol,
                    "positions_count": len(positions_data),
                }

            except Exception as exc:
                runtime.connected = False
                runtime.readiness_verified = False
                runtime.trading_enabled = False
                runtime.last_error = str(exc)

                logger.warning(
                    "Account connection/readiness failed for %s: %s",
                    runtime.account_id,
                    exc,
                )

                return {
                    "success": False,
                    "account_id": runtime.account_id,
                    "connected": False,
                    "readiness_verified": False,
                    "error": str(exc),
                }

    async def refresh_account(self, account_id: str) -> dict[str, Any]:
        """
        Refresh broker account, position, and price snapshots.

        Does not change trading strategy or automatically close positions.
        """

        runtime = self._get_runtime(account_id)

        async with runtime.lock:
            try:
                client = self.connector.get_client(runtime.account_id)

                if client is None:
                    raise RuntimeError("Account client is not connected")

                snapshot = await client.get_broker_snapshot(
                    account_id=runtime.account_id,
                    symbol=runtime.symbol,
                )

                if not isinstance(snapshot, dict):
                    raise RuntimeError("Invalid broker snapshot")

                account_data = snapshot.get("account")
                positions_data = snapshot.get("positions")
                price_data = snapshot.get("price")

                if not isinstance(account_data, dict):
                    raise RuntimeError("Account snapshot unavailable")

                if not isinstance(positions_data, list):
                    raise RuntimeError("Positions snapshot unavailable")

                runtime.account_snapshot = account_data
                runtime.positions_snapshot = positions_data
                runtime.price_snapshot = price_data
                runtime.last_check_time = time.time()
                runtime.last_error = None

                return {
                    "success": True,
                    "account_id": runtime.account_id,
                    "positions_count": len(positions_data),
                }

            except Exception as exc:
                runtime.last_error = str(exc)

                logger.warning(
                    "Account refresh failed for %s: %s",
                    runtime.account_id,
                    exc,
                )

                return {
                    "success": False,
                    "account_id": runtime.account_id,
                    "error": str(exc),
                }

    # ------------------------------------------------------------------
    # Start / stop trading
    # ------------------------------------------------------------------

    async def start_account(self, account_id: str) -> dict[str, Any]:
        """
        Start the injected trading engine for an account.

        Required sequence:
        1. Connect and verify broker state.
        2. Reconcile broker positions with the engine.
        3. Start the engine callback.
        4. Mark trading enabled only after callback success.

        No strategy is invented here.
        """

        runtime = self._get_runtime(account_id)

        async with runtime.lock:
            if runtime.trading_enabled:
                return {
                    "success": True,
                    "account_id": runtime.account_id,
                    "trading_enabled": True,
                    "already_running": True,
                }

            if self.start_callback is None:
                return {
                    "success": False,
                    "account_id": runtime.account_id,
                    "trading_enabled": False,
                    "error": "No trading engine start_callback is configured",
                }

            readiness = await self.connect_account(runtime.account_id)

            if not readiness.get("success"):
                return {
                    "success": False,
                    "account_id": runtime.account_id,
                    "trading_enabled": False,
                    "error": readiness.get("error", "Account not ready"),
                }

            snapshot = {
                "account": runtime.account_snapshot,
                "positions": runtime.positions_snapshot,
                "price": runtime.price_snapshot,
                "symbol": runtime.symbol,
            }

            try:
                # Reconcile live broker positions before starting new entries.
                await self._invoke_callback(
                    self.reconcile_callback,
                    runtime.account_id,
                    snapshot,
                )

                start_result = await self._invoke_callback(
                    self.start_callback,
                    runtime.account_id,
                    snapshot,
                )

                if isinstance(start_result, dict):
                    if start_result.get("success") is False:
                        raise RuntimeError(
                            start_result.get(
                                "error",
                                "Trading engine refused to start",
                            )
                        )

                if start_result is False:
                    raise RuntimeError("Trading engine refused to start")

                runtime.trading_enabled = True
                runtime.runtime_started_at = time.time()
                runtime.last_error = None

                return {
                    "success": True,
                    "account_id": runtime.account_id,
                    "trading_enabled": True,
                    "positions_reconciled": True,
                }

            except Exception as exc:
                runtime.trading_enabled = False
                runtime.last_error = str(exc)

                logger.exception(
                    "Could not start trading for account %s",
                    runtime.account_id,
                )

                return {
                    "success": False,
                    "account_id": runtime.account_id,
                    "trading_enabled": False,
                    "error": str(exc),
                }

    async def stop_account(self, account_id: str) -> dict[str, Any]:
        """
        Stop new engine activity for one account.

        This does not automatically close broker positions. Existing
        positions remain protected by their broker-side SL/TP.
        """

        runtime = self._get_runtime(account_id)

        async with runtime.lock:
            try:
                await self._invoke_callback(
                    self.stop_callback,
                    runtime.account_id,
                )

                runtime.trading_enabled = False
                runtime.runtime_started_at = None

                return {
                    "success": True,
                    "account_id": runtime.account_id,
                    "trading_enabled": False,
                    "positions_closed": False,
                }

            except Exception as exc:
                runtime.last_error = str(exc)

                logger.exception(
                    "Could not stop trading for account %s",
                    runtime.account_id,
                )

                return {
                    "success": False,
                    "account_id": runtime.account_id,
                    "trading_enabled": runtime.trading_enabled,
                    "error": str(exc),
                }

    # ------------------------------------------------------------------
    # Disconnect / remove
    # ------------------------------------------------------------------

    async def disconnect_account(
        self,
        account_id: str,
        *,
        stop_trading: bool = True,
    ) -> dict[str, Any]:
        runtime = self._get_runtime(account_id)

        if stop_trading and runtime.trading_enabled:
            stop_result = await self.stop_account(account_id)

            if not stop_result.get("success"):
                return stop_result

        async with runtime.lock:
            try:
                await self.connector.disconnect_account(
                    runtime.account_id
                )

                runtime.connected = False
                runtime.readiness_verified = False

                return {
                    "success": True,
                    "account_id": runtime.account_id,
                    "connected": False,
                    "trading_enabled": runtime.trading_enabled,
                }

            except Exception as exc:
                runtime.last_error = str(exc)

                return {
                    "success": False,
                    "account_id": runtime.account_id,
                    "error": str(exc),
                }

    async def remove_account(self, account_id: str) -> dict[str, Any]:
        runtime = self._get_runtime(account_id)

        if runtime.trading_enabled:
            stop_result = await self.stop_account(account_id)

            if not stop_result.get("success"):
                return stop_result

        await self.disconnect_account(
            account_id,
            stop_trading=False,
        )

        async with self._registry_lock:
            self._accounts.pop(runtime.account_id, None)

        await self.connector.remove_account(runtime.account_id)

        return {
            "success": True,
            "account_id": runtime.account_id,
            "removed": True,
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_account_status(self, account_id: str) -> dict[str, Any]:
        runtime = self._get_runtime(account_id)

        return {
            "account_id": runtime.account_id,
            "symbol": runtime.symbol,
            "registered": runtime.registered,
            "connected": runtime.connected,
            "readiness_verified": runtime.readiness_verified,
            "trading_enabled": runtime.trading_enabled,
            "positions_count": len(runtime.positions_snapshot),
            "last_check_time": runtime.last_check_time,
            "runtime_started_at": runtime.runtime_started_at,
            "last_error": runtime.last_error,
        }

    def get_all_account_statuses(self) -> list[dict[str, Any]]:
        return [
            self.get_account_status(account_id)
            for account_id in list(self._accounts.keys())
        ]

    async def shutdown(self) -> None:
        """
        Gracefully stop account engines and disconnect accounts.

        Does not close open broker positions.
        """

        account_ids = list(self._accounts.keys())

        for account_id in account_ids:
            runtime = self._accounts.get(account_id)

            if runtime is None:
                continue

            if runtime.trading_enabled:
                await self.stop_account(account_id)

            await self.disconnect_account(
                account_id,
                stop_trading=False,
            )

        await self.connector.shutdown()
