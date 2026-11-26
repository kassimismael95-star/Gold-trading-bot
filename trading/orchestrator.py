
"""
GOLD SCALPER AI
Account and engine orchestration.

Responsibilities:
- Wire AccountManager to EngineRegistry.
- Keep engine instances isolated by account.
- Route account registration, start, stop, status and shutdown.
- Avoid placing trading strategy or risk rules in this layer.

The actual trading engine must be supplied through engine_factory.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, Optional

from .account_manager import AccountManager
from .engine_registry import EngineRegistry


logger = logging.getLogger(__name__)


class TradingOrchestrator:
    """
    Central lifecycle coordinator for multiple trading accounts.

    engine_factory(account_id, account_config) must return an engine
    instance implementing the methods expected by EngineRegistry.

    This class does not create or modify trading signals.
    """

    def __init__(
        self,
        connector: Any,
        engine_factory: Callable[[str, Dict[str, Any]], Any],
    ) -> None:
        if connector is None:
            raise ValueError("connector is required")

        if not callable(engine_factory):
            raise TypeError("engine_factory must be callable")

        self.connector = connector
        self._closed = False
        self._shutdown_lock = asyncio.Lock()

        self.engine_registry = EngineRegistry(
            engine_factory=engine_factory
        )

        self.account_manager = AccountManager(
            connector=connector,
            reconcile_callback=(
                self.engine_registry.account_manager_reconcile_callback
            ),
            start_callback=(
                self.engine_registry.account_manager_start_callback
            ),
            stop_callback=(
                self.engine_registry.account_manager_stop_callback
            ),
        )

    @staticmethod
    async def _call_maybe_async(
        function: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Call a synchronous or asynchronous function safely.

        Synchronous functions are executed in a worker thread so they
        don't block the event loop.
        """
        if inspect.iscoroutinefunction(function):
            return await function(*args, **kwargs)

        result = await asyncio.to_thread(
            function,
            *args,
            **kwargs,
        )

        if inspect.isawaitable(result):
            return await result

        return result

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("TradingOrchestrator is shut down")

    async def register_account(
        self,
        account_id: str,
        account_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Register an account with the account manager and connector.

        account_config is passed through unchanged. Do not log passwords,
        tokens, or other account credentials.
        """
        self._ensure_open()

        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("account_id must be a non-empty string")

        if not isinstance(account_config, dict):
            raise TypeError("account_config must be a dictionary")

        try:
            result = await self._call_maybe_async(
                self.account_manager.register_account,
                account_id,
                account_config,
            )

            return {
                "success": True,
                "account_id": account_id,
                "result": result,
            }

        except Exception:
            logger.exception(
                "Account registration failed for account_id=%s",
                account_id,
            )
            return {
                "success": False,
                "account_id": account_id,
                "error": "Account registration failed",
            }

    async def start_account(
        self,
        account_id: str,
    ) -> Dict[str, Any]:
        """
        Connect and start the account's engine through AccountManager.

        AccountManager and EngineRegistry are responsible for reconciling
        broker positions before the engine begins trading.
        """
        self._ensure_open()

        try:
            result = await self._call_maybe_async(
                self.account_manager.start_account,
                account_id,
            )

            return {
                "success": True,
                "account_id": account_id,
                "result": result,
            }

        except Exception:
            logger.exception(
                "Account start failed for account_id=%s",
                account_id,
            )
            return {
                "success": False,
                "account_id": account_id,
                "error": "Account could not be started",
            }

    async def stop_account(
        self,
        account_id: str,
    ) -> Dict[str, Any]:
        """
        Stop the account's engine.

        This requests an engine stop; it does not automatically close
        broker positions unless the engine's stop behavior explicitly
        implements that policy.
        """
        self._ensure_open()

        try:
            result = await self._call_maybe_async(
                self.account_manager.stop_account,
                account_id,
            )

            return {
                "success": True,
                "account_id": account_id,
                "result": result,
            }

        except Exception:
            logger.exception(
                "Account stop failed for account_id=%s",
                account_id,
            )
            return {
                "success": False,
                "account_id": account_id,
                "error": "Account could not be stopped",
            }

    async def get_account_status(
        self,
        account_id: str,
    ) -> Dict[str, Any]:
        """Return account-manager and engine-registry status."""
        self._ensure_open()

        account_status = await self._call_maybe_async(
            self.account_manager.get_account_status,
            account_id,
        )

        engine_status = self.engine_registry.get_status(
            account_id
        )

        return {
            "account_id": account_id,
            "account": account_status,
            "engine": engine_status,
        }

    async def get_all_statuses(self) -> Dict[str, Any]:
        """Return status for all accounts known to the account manager."""
        self._ensure_open()

        account_statuses = await self._call_maybe_async(
            self.account_manager.get_all_statuses
        )

        engine_statuses = self.engine_registry.get_all_statuses()

        return {
            "accounts": account_statuses,
            "engines": engine_statuses,
        }

    async def remove_account(
        self,
        account_id: str,
    ) -> Dict[str, Any]:
        """
        Remove an account after asking AccountManager to disconnect it.

        AccountManager must reject removal if disconnecting fails.
        """
        self._ensure_open()

        try:
            result = await self._call_maybe_async(
                self.account_manager.remove_account,
                account_id,
            )

            if result is False:
                return {
                    "success": False,
                    "account_id": account_id,
                    "error": "Account manager refused removal",
                }

            await self._call_maybe_async(
                self.engine_registry.remove_account,
                account_id,
            )

            return {
                "success": True,
                "account_id": account_id,
                "result": result,
            }

        except Exception:
            logger.exception(
                "Account removal failed for account_id=%s",
                account_id,
            )
            return {
                "success": False,
                "account_id": account_id,
                "error": "Account could not be removed",
            }

    async def shutdown(self) -> None:
        """
        Stop orchestration and release account/engine resources.

        Shutdown is idempotent.
        """
        async with self._shutdown_lock:
            if self._closed:
                return

            self._closed = True

            shutdown_errors = []

            for component_name, component in (
                ("account_manager", self.account_manager),
                ("engine_registry", self.engine_registry),
                ("connector", self.connector),
            ):
                shutdown_method = getattr(
                    component,
                    "shutdown",
                    None,
                )

                if not callable(shutdown_method):
                    continue

                try:
                    await self._call_maybe_async(
                        shutdown_method
                    )
                except Exception:
                    shutdown_errors.append(component_name)
                    logger.exception(
                        "Shutdown failed for component=%s",
                        component_name,
                    )

            if shutdown_errors:
                logger.error(
                    "Orchestrator shutdown completed with errors: %s",
                    ", ".join(shutdown_errors),
                )

    async def __aenter__(self) -> "TradingOrchestrator":
        self._ensure_open()
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        await self.shutdown()
