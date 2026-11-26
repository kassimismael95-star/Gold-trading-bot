
"""
Gold Scalper AI
File: trading/engine_registry.py

Per-account trading engine registry.

This module:
- Maintains isolated engine instances per account.
- Provides callbacks for AccountManager.
- Starts and stops each account's engine independently.
- Supports broker-position reconciliation before trading starts.

The original trading engine is injected through engine_factory.
No strategy, lot sizing, trading thresholds, or entry rules are defined here.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)

EngineFactory = Callable[[str, dict[str, Any]], Any]
Callback = Callable[..., Any]


@dataclass
class EngineRecord:
    account_id: str
    engine: Any

    running: bool = False
    reconciled: bool = False
    last_error: Optional[str] = None

    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class EngineRegistry:
    """
    Registry for independent trading engines.

    engine_factory(account_id, account_snapshot) must return the original
    engine instance for that account.

    Expected optional engine methods:
        start()
        stop()
        reconcile_positions(positions)

    Methods may be synchronous or asynchronous.

    If the original engine uses different method names or signatures,
    adapt it inside the supplied engine_factory or a small wrapper class.
    """

    def __init__(
        self,
        engine_factory: EngineFactory,
    ) -> None:
        if not callable(engine_factory):
            raise ValueError("engine_factory must be callable")

        self.engine_factory = engine_factory
        self._records: dict[str, EngineRecord] = {}
        self._registry_lock = asyncio.Lock()

    async def _invoke(
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

    def _get_record(self, account_id: str) -> EngineRecord:
        record = self._records.get(str(account_id))

        if record is None:
            raise KeyError(
                f"No engine registered for account: {account_id}"
            )

        return record

    async def create_engine(
        self,
        account_id: str,
        account_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        account_id = str(account_id)

        async with self._registry_lock:
            existing = self._records.get(account_id)

            if existing is not None:
                return {
                    "success": True,
                    "account_id": account_id,
                    "created": False,
                    "already_registered": True,
                }

            engine = await self._invoke(
                self.engine_factory,
                account_id,
                account_snapshot,
            )

            if engine is None:
                raise RuntimeError(
                    "engine_factory returned no engine instance"
                )

            self._records[account_id] = EngineRecord(
                account_id=account_id,
                engine=engine,
            )

        return {
            "success": True,
            "account_id": account_id,
            "created": True,
        }

    async def reconcile_account(
        self,
        account_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Reconcile engine state against current broker positions.

        This callback should run before the engine starts opening new trades.
        """

        record = self._get_record(account_id)

        async with record.lock:
            try:
                if not isinstance(snapshot, dict):
                    raise ValueError("Invalid account snapshot")

                positions = snapshot.get("positions")

                if not isinstance(positions, list):
                    raise ValueError(
                        "Broker positions must be provided as a list"
                    )

                method = getattr(
                    record.engine,
                    "reconcile_positions",
                    None,
                )

                if callable(method):
                    result = await self._invoke(method, positions)

                    if result is False:
                        raise RuntimeError(
                            "Engine refused broker position reconciliation"
                        )

                    if (
                        isinstance(result, dict)
                        and result.get("success") is False
                    ):
                        raise RuntimeError(
                            result.get(
                                "error",
                                "Position reconciliation failed",
                            )
                        )

                record.reconciled = True
                record.last_error = None

                return {
                    "success": True,
                    "account_id": record.account_id,
                    "positions_reconciled": True,
                    "positions_count": len(positions),
                }

            except Exception as exc:
                record.reconciled = False
                record.last_error = str(exc)

                logger.exception(
                    "Engine reconciliation failed for account %s",
                    record.account_id,
                )

                return {
                    "success": False,
                    "account_id": record.account_id,
                    "error": str(exc),
                }

    async def start_account(
        self,
        account_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Start one account engine.

        Engine creation and reconciliation must have completed first.
        """

        record = self._get_record(account_id)

        async with record.lock:
            if record.running:
                return {
                    "success": True,
                    "account_id": record.account_id,
                    "running": True,
                    "already_running": True,
                }

            if not record.reconciled:
                return {
                    "success": False,
                    "account_id": record.account_id,
                    "running": False,
                    "error": "Engine has not reconciled broker positions",
                }

            try:
                method = getattr(record.engine, "start", None)

                if not callable(method):
                    raise RuntimeError(
                        "Engine does not provide a start() method"
                    )

                result = await self._invoke(method)

                if result is False:
                    raise RuntimeError("Engine refused to start")

                if (
                    isinstance(result, dict)
                    and result.get("success") is False
                ):
                    raise RuntimeError(
                        result.get(
                            "error",
                            "Engine refused to start",
                        )
                    )

                record.running = True
                record.last_error = None

                return {
                    "success": True,
                    "account_id": record.account_id,
                    "running": True,
                }

            except Exception as exc:
                record.running = False
                record.last_error = str(exc)

                logger.exception(
                    "Engine start failed for account %s",
                    record.account_id,
                )

                return {
                    "success": False,
                    "account_id": record.account_id,
                    "running": False,
                    "error": str(exc),
                }

    async def stop_account(
        self,
        account_id: str,
    ) -> dict[str, Any]:
        record = self._get_record(account_id)

        async with record.lock:
            if not record.running:
                return {
                    "success": True,
                    "account_id": record.account_id,
                    "running": False,
                    "already_stopped": True,
                }

            try:
                method = getattr(record.engine, "stop", None)

                if not callable(method):
                    raise RuntimeError(
                        "Engine does not provide a stop() method"
                    )

                result = await self._invoke(method)

                if result is False:
                    raise RuntimeError("Engine refused to stop")

                if (
                    isinstance(result, dict)
                    and result.get("success") is False
                ):
                    raise RuntimeError(
                        result.get(
                            "error",
                            "Engine refused to stop",
                        )
                    )

                record.running = False
                record.last_error = None

                return {
                    "success": True,
                    "account_id": record.account_id,
                    "running": False,
                }

            except Exception as exc:
                record.last_error = str(exc)

                logger.exception(
                    "Engine stop failed for account %s",
                    record.account_id,
                )

                return {
                    "success": False,
                    "account_id": record.account_id,
                    "running": record.running,
                    "error": str(exc),
                }

    async def remove_account(
        self,
        account_id: str,
    ) -> dict[str, Any]:
        record = self._get_record(account_id)

        if record.running:
            result = await self.stop_account(account_id)

            if not result.get("success"):
                return result

        async with self._registry_lock:
            self._records.pop(record.account_id, None)

        return {
            "success": True,
            "account_id": record.account_id,
            "removed": True,
        }

    def get_status(
        self,
        account_id: str,
    ) -> dict[str, Any]:
        record = self._get_record(account_id)

        return {
            "account_id": record.account_id,
            "running": record.running,
            "reconciled": record.reconciled,
            "last_error": record.last_error,
        }

    def get_all_statuses(self) -> list[dict[str, Any]]:
        return [
            self.get_status(account_id)
            for account_id in list(self._records.keys())
        ]

    # ------------------------------------------------------------------
    # AccountManager callback adapters
    # ------------------------------------------------------------------

    async def account_manager_reconcile_callback(
        self,
        account_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create the account engine if needed, then reconcile it.
        """

        if account_id not in self._records:
            await self.create_engine(
                account_id,
                snapshot,
            )

        return await self.reconcile_account(
            account_id,
            snapshot,
        )

    async def account_manager_start_callback(
        self,
        account_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Callback for AccountManager.start_callback.
        """

        if account_id not in self._records:
            await self.create_engine(
                account_id,
                snapshot,
            )

        record = self._get_record(account_id)

        if not record.reconciled:
            reconciliation = await self.reconcile_account(
                account_id,
                snapshot,
            )

            if not reconciliation.get("success"):
                return reconciliation

        return await self.start_account(
            account_id,
            snapshot,
        )

    async def account_manager_stop_callback(
        self,
        account_id: str,
    ) -> dict[str, Any]:
        """
        Callback for AccountManager.stop_callback.
        """

        if account_id not in self._records:
            return {
                "success": True,
                "account_id": str(account_id),
                "running": False,
                "engine_not_registered": True,
            }

        return await self.stop_account(account_id)

    async def shutdown(self) -> None:
        for account_id in list(self._records.keys()):
            record = self._records.get(account_id)

            if record is None or not record.running:
                continue

            await self.stop_account(account_id)
