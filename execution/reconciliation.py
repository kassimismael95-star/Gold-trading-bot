import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


@dataclass
class ReconciliationResult:
    account_id: str
    worker_id: str | None
    checked_at: datetime
    worker_online: bool
    mt5_connected: bool
    pending_commands: int
    duplicate_risk_detected: bool
    missing_fill_detected: bool
    stale_position_detected: bool
    action_taken: str
    details: dict[str, Any]


class ReconciliationService:
    """
    Detects execution problems without changing the original
    Gold Scalper trading style.

    Detects:
    - Offline workers
    - Disconnected MT5 sessions
    - Pending commands that were never confirmed
    - Possible duplicate orders
    - Missing fills
    - Stale positions
    """

    PENDING_COMMAND_TIMEOUT_SECONDS = 30
    STALE_POSITION_TIMEOUT_SECONDS = 120

    def __init__(self, database, worker_registry):
        self.database = database
        self.worker_registry = worker_registry

    def _worker_status_url(self, worker_id: str) -> str:
        base_url = os.environ.get("WORKER_API_URL", "").strip().rstrip("/")

        if not base_url:
            raise ValueError(
                "WORKER_API_URL is empty. "
                "Set it in the Render environment variables."
            )

        return f"{base_url}/workers/{worker_id}/status"

    async def reconcile_account(self, account_id: str) -> ReconciliationResult:
        now = datetime.now(timezone.utc)

        account = self.database.get_account(account_id)

        if not account:
            return ReconciliationResult(
                account_id=account_id,
                worker_id=None,
                checked_at=now,
                worker_online=False,
                mt5_connected=False,
                pending_commands=0,
                duplicate_risk_detected=False,
                missing_fill_detected=False,
                stale_position_detected=False,
                action_taken="ACCOUNT_NOT_FOUND",
                details={},
            )

        worker_id = account.get("worker_id")

        if not worker_id:
            return ReconciliationResult(
                account_id=account_id,
                worker_id=None,
                checked_at=now,
                worker_online=False,
                mt5_connected=False,
                pending_commands=0,
                duplicate_risk_detected=False,
                missing_fill_detected=False,
                stale_position_detected=False,
                action_taken="NO_WORKER_ASSIGNED",
                details={},
            )

        worker = self.worker_registry.get_worker(worker_id)

        worker_online = bool(
            worker
            and worker.get("status") == "ACTIVE"
        )

        pending_commands = self.database.get_pending_commands(account_id)

        duplicate_risk = self._detect_duplicate_risk(pending_commands)

        missing_fill = self._detect_missing_fill(
            pending_commands,
            now,
        )

        stale_position = self._detect_stale_position(
            account,
            now,
        )

        mt5_connected = False
        action_taken = "NO_ACTION"

        if worker_online:
            mt5_connected = await self._check_worker_mt5_connection(
                worker_id
            )

        if not worker_online:
            action_taken = "WORKER_OFFLINE"

        elif not mt5_connected:
            action_taken = "MT5_DISCONNECTED"

        elif duplicate_risk:
            action_taken = "DUPLICATE_RISK_DETECTED"

        elif missing_fill:
            action_taken = "MISSING_FILL_DETECTED"

        elif stale_position:
            action_taken = "STALE_POSITION_DETECTED"

        elif pending_commands:
            action_taken = "PENDING_COMMANDS_WAITING"

        return ReconciliationResult(
            account_id=account_id,
            worker_id=worker_id,
            checked_at=now,
            worker_online=worker_online,
            mt5_connected=mt5_connected,
            pending_commands=len(pending_commands),
            duplicate_risk_detected=duplicate_risk,
            missing_fill_detected=missing_fill,
            stale_position_detected=stale_position,
            action_taken=action_taken,
            details={
                "pending_command_ids": [
                    command.get("id")
                    for command in pending_commands
                ],
            },
        )

    def _detect_duplicate_risk(
        self,
        pending_commands: list[dict],
    ) -> bool:
        seen_keys = set()

        for command in pending_commands:
            command_type = str(
                command.get("command_type", "")
            ).strip().upper()

            if command_type not in ["BUY", "SELL"]:
                continue

            duplicate_key = (
                command.get("account_id"),
                command.get("symbol"),
                command_type,
                command.get("volume"),
                command.get("stop_loss"),
                command.get("take_profit"),
            )

            if duplicate_key in seen_keys:
                return True

            seen_keys.add(duplicate_key)

        return False

    def _detect_missing_fill(
        self,
        pending_commands: list[dict],
        now: datetime,
    ) -> bool:
        timeout = timedelta(
            seconds=self.PENDING_COMMAND_TIMEOUT_SECONDS
        )

        for command in pending_commands:
            created_at = command.get("created_at")

            if not created_at:
                continue

            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )

                except Exception:
                    continue

            if now - created_at > timeout:
                return True

        return False

    def _detect_stale_position(
        self,
        account: dict,
        now: datetime,
    ) -> bool:
        last_position_update = account.get("last_position_update_at")

        if not last_position_update:
            return False

        if isinstance(last_position_update, str):
            try:
                last_position_update = datetime.fromisoformat(
                    last_position_update.replace("Z", "+00:00")
                )

            except Exception:
                return False

        stale_limit = timedelta(
            seconds=self.STALE_POSITION_TIMEOUT_SECONDS
        )

        return now - last_position_update > stale_limit

    async def _check_worker_mt5_connection(
        self,
        worker_id: str,
    ) -> bool:
        shared_secret = os.environ.get("WORKER_SHARED_SECRET", "").strip()

        if not shared_secret:
            return False

        url = self._worker_status_url(worker_id)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    headers={
                        "X-Worker-Secret": shared_secret,
                    },
                )

            if response.status_code != 200:
                return False

            data = response.json()

            return bool(
                data.get("mt5_connected", False)
            )

        except Exception:
            return False
