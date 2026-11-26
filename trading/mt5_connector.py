
"""
GOLD SCALPER AI
File: trading/mt5_connector.py

MT5 account connection and lifecycle manager.

Responsibilities:
    - Register account-specific Oracle bridge connections
    - Check bridge health
    - Verify MT5 account information
    - Maintain isolated connection status
    - Support reconnecting after temporary failures
    - Safely remove account connections

No MetaApi.
No trading strategy.
No order execution rules.
"""

from __future__ import annotations

import asyncio
import logging
import time

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from trading.broker_adapter import (
    MetaTraderBrokerAdapter,
    MT5BridgeClient,
    BrokerAdapterError,
)


logger = logging.getLogger(
    "gold_scalper.mt5_connector"
)


# ============================================================
# CONNECTION STATES
# ============================================================

class ConnectionState(str, Enum):

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    STOPPED = "stopped"


# ============================================================
# ACCOUNT CONNECTION RECORD
# ============================================================

@dataclass
class MT5AccountConnection:

    account_id: str

    bridge_url: str

    api_key: str = field(repr=False)

    timeout: float = 10.0

    state: ConnectionState = (
        ConnectionState.DISCONNECTED
    )

    connected_at: Optional[float] = None

    last_successful_check: Optional[float] = None

    last_error: Optional[str] = None

    reconnect_attempts: int = 0

    broker_login: Optional[str] = None

    broker_server: Optional[str] = None

    _client: Optional[MT5BridgeClient] = field(
        default=None,
        repr=False,
    )

    _lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        repr=False,
    )

    def public_status(self) -> dict:

        return {
            "account_id": self.account_id,
            "state": self.state.value,
            "connected": (
                self.state == ConnectionState.CONNECTED
            ),
            "connected_at": self.connected_at,
            "last_successful_check": (
                self.last_successful_check
            ),
            "last_error": self.last_error,
            "reconnect_attempts": (
                self.reconnect_attempts
            ),
            "broker_login": self.broker_login,
            "broker_server": self.broker_server,
        }


# ============================================================
# MT5 CONNECTOR
# ============================================================

class MT5Connector:

    def __init__(
        self,
        broker_adapter: Optional[
            MetaTraderBrokerAdapter
        ] = None,
    ):

        self.broker_adapter = (
            broker_adapter
            or MetaTraderBrokerAdapter()
        )

        self._accounts: dict[
            str,
            MT5AccountConnection
        ] = {}

        self._registry_lock = asyncio.Lock()

        self._shutdown = False

    # ========================================================
    # REGISTER ACCOUNT
    # ========================================================

    async def register_account(
        self,
        account_id: str,
        bridge_url: str,
        api_key: str,
        timeout: float = 10.0,
    ) -> MT5AccountConnection:

        if self._shutdown:
            raise RuntimeError(
                "Connector has been shut down"
            )

        if not account_id or not account_id.strip():
            raise ValueError(
                "account_id is required"
            )

        if not bridge_url or not bridge_url.strip():
            raise ValueError(
                "bridge_url is required"
            )

        if not api_key or not api_key.strip():
            raise ValueError(
                "api_key is required"
            )

        account_id = account_id.strip()

        async with self._registry_lock:

            existing = self._accounts.get(
                account_id
            )

            if existing is not None:
                await self._disconnect_record(
                    existing
                )

            record = MT5AccountConnection(
                account_id=account_id,
                bridge_url=bridge_url.rstrip("/"),
                api_key=api_key,
                timeout=timeout,
            )

            self._accounts[account_id] = record

        return record

    # ========================================================
    # CONNECT ACCOUNT
    # ========================================================

    async def connect_account(
        self,
        account_id: str,
    ) -> dict:

        record = self._get_record(account_id)

        async with record._lock:

            if record.state == ConnectionState.CONNECTED:
                return record.public_status()

            record.state = ConnectionState.CONNECTING
            record.last_error = None

            try:

                client = await self.broker_adapter.register_account(
                    account_id=record.account_id,
                    bridge_url=record.bridge_url,
                    api_key=record.api_key,
                    timeout=record.timeout,
                )

                record._client = client

                # Verify that the Oracle bridge responds.
                await client.health_check()

                # Verify that the EA has published account state.
                account_info = (
                    await client.get_account_information()
                )

                if not isinstance(account_info, dict):
                    raise BrokerAdapterError(
                        "Invalid MT5 account information"
                    )

                record.broker_login = str(
                    account_info.get("login", "")
                ) or None

                record.broker_server = (
                    account_info.get("server")
                )

                record.state = ConnectionState.CONNECTED

                record.connected_at = time.time()

                record.last_successful_check = (
                    record.connected_at
                )

                record.last_error = None

                record.reconnect_attempts = 0

                logger.info(
                    "MT5 bridge connected for account %s",
                    record.account_id,
                )

                return record.public_status()

            except Exception as exc:

                record.state = ConnectionState.ERROR

                record.last_error = str(exc)

                logger.warning(
                    "MT5 connection failed for account %s: %s",
                    record.account_id,
                    exc,
                )

                raise

    # ========================================================
    # DISCONNECT ACCOUNT
    # ========================================================

    async def disconnect_account(
        self,
        account_id: str,
    ) -> dict:

        record = self._get_record(account_id)

        async with record._lock:

            await self._disconnect_record(
                record
            )

            record.state = ConnectionState.DISCONNECTED

            return record.public_status()

    async def _disconnect_record(
        self,
        record: MT5AccountConnection,
    ):

        try:

            await self.broker_adapter.remove_account(
                record.account_id
            )

        except Exception as exc:

            logger.warning(
                "Error removing bridge client for account %s: %s",
                record.account_id,
                exc,
            )

        record._client = None

        record.connected_at = None

    # ========================================================
    # CONNECTION CHECK
    # ========================================================

    async def check_connection(
        self,
        account_id: str,
    ) -> dict:

        record = self._get_record(account_id)

        async with record._lock:

            if record._client is None:
                record.state = (
                    ConnectionState.DISCONNECTED
                )

                return record.public_status()

            try:

                await record._client.health_check()

                account_info = (
                    await record._client.get_account_information()
                )

                record.broker_login = str(
                    account_info.get("login", "")
                ) or None

                record.broker_server = (
                    account_info.get("server")
                )

                record.state = (
                    ConnectionState.CONNECTED
                )

                record.last_successful_check = (
                    time.time()
                )

                record.last_error = None

            except Exception as exc:

                record.state = (
                    ConnectionState.ERROR
                )

                record.last_error = str(exc)

                logger.warning(
                    "Connection check failed for account %s",
                    record.account_id,
                )

            return record.public_status()

    # ========================================================
    # RECONNECT ACCOUNT
    # ========================================================

    async def reconnect_account(
        self,
        account_id: str,
    ) -> dict:

        record = self._get_record(account_id)

        async with record._lock:

            record.state = (
                ConnectionState.RECONNECTING
            )

            record.reconnect_attempts += 1

            await self._disconnect_record(
                record
            )

            try:

                client = await self.broker_adapter.register_account(
                    account_id=record.account_id,
                    bridge_url=record.bridge_url,
                    api_key=record.api_key,
                    timeout=record.timeout,
                )

                record._client = client

                await client.health_check()

                account_info = (
                    await client.get_account_information()
                )

                record.broker_login = str(
                    account_info.get("login", "")
                ) or None

                record.broker_server = (
                    account_info.get("server")
                )

                record.state = (
                    ConnectionState.CONNECTED
                )

                record.connected_at = time.time()

                record.last_successful_check = (
                    record.connected_at
                )

                record.last_error = None

                logger.info(
                    "MT5 bridge reconnected for account %s",
                    record.account_id,
                )

                return record.public_status()

            except Exception as exc:

                record.state = ConnectionState.ERROR

                record.last_error = str(exc)

                logger.warning(
                    "Reconnect failed for account %s: %s",
                    record.account_id,
                    exc,
                )

                raise

    # ========================================================
    # GET ACCOUNT CLIENT
    # ========================================================

    async def get_client(
        self,
        account_id: str,
    ) -> MT5BridgeClient:

        record = self._get_record(account_id)

        if record.state != ConnectionState.CONNECTED:
            raise BrokerAdapterError(
                f"Account {account_id} is not connected"
            )

        if record._client is None:
            raise BrokerAdapterError(
                f"No bridge client exists for account {account_id}"
            )

        return record._client

    # ========================================================
    # ACCOUNT STATUS
    # ========================================================

    def get_connection_status(
        self,
        account_id: str,
    ) -> dict:

        record = self._get_record(account_id)

        return record.public_status()

    def get_all_connection_statuses(self) -> list[dict]:

        return [
            record.public_status()
            for record in self._accounts.values()
        ]

    # ========================================================
    # REMOVE ACCOUNT
    # ========================================================

    async def remove_account(
        self,
        account_id: str,
    ):

        async with self._registry_lock:

            record = self._accounts.pop(
                account_id,
                None
            )

        if record is None:
            return

        async with record._lock:

            await self._disconnect_record(
                record
            )

            record.state = (
                ConnectionState.STOPPED
            )

            record.api_key = ""

    # ========================================================
    # INTERNAL
    # ========================================================

    def _get_record(
        self,
        account_id: str,
    ) -> MT5AccountConnection:

        record = self._accounts.get(
            account_id
        )

        if record is None:
            raise KeyError(
                f"Account {account_id} is not registered"
            )

        return record

    # ========================================================
    # SHUTDOWN
    # ========================================================

    async def shutdown(self):

        self._shutdown = True

        account_ids = list(
            self._accounts.keys()
        )

        for account_id in account_ids:

            try:
                await self.remove_account(
                    account_id
                )

            except Exception as exc:

                logger.warning(
                    "Error shutting down account %s: %s",
                    account_id,
                    exc,
                )

        await self.broker_adapter.close()


# ============================================================
# COMPATIBILITY ALIAS
# ============================================================

MT5ConnectionManager = MT5Connector
