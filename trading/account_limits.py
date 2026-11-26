
import threading
from datetime import datetime, timezone
from typing import Dict, Optional


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class AccountExecutionRegistry:
    """
    Isolates execution permissions and trading state per account.

    Responsibilities:
    - Track registered trading accounts.
    - Track account connection state.
    - Track bot running/stopped state.
    - Track risk-supervisor entry blocks.
    - Track account-specific execution permissions.
    - Prevent accidental cross-account state access.

    This class does not decide trading strategy or lot sizing.
    """

    def __init__(self):
        self.accounts: Dict[str, dict] = {}
        self.lock = threading.RLock()

    def register_account(
        self,
        account_id,
        license_key,
        mt5_login,
        mt5_server,
        symbol
    ):
        account_id = str(account_id)

        if not account_id:
            raise ValueError("Account ID is required")

        if not license_key:
            raise ValueError("License key is required")

        if not mt5_login:
            raise ValueError("MT5 login is required")

        if not mt5_server:
            raise ValueError("MT5 server is required")

        if not symbol:
            raise ValueError("Trading symbol is required")

        with self.lock:
            existing = self.accounts.get(account_id)

            if existing:
                if existing["license_key"] != str(license_key):
                    raise ValueError(
                        "Account license ownership mismatch"
                    )

                existing.update({
                    "mt5_login": str(mt5_login),
                    "mt5_server": str(mt5_server),
                    "symbol": str(symbol),
                    "updated_at": utc_now()
                })

                return self._public_state(existing)

            state = {
                "account_id": account_id,
                "license_key": str(license_key),
                "mt5_login": str(mt5_login),
                "mt5_server": str(mt5_server),
                "symbol": str(symbol),

                "connected": False,
                "running": False,

                "entry_blocked": False,
                "entry_block_reason": None,

                "execution_enabled": True,

                "last_connection_at": None,
                "last_started_at": None,
                "last_stopped_at": None,

                "created_at": utc_now(),
                "updated_at": utc_now()
            }

            self.accounts[account_id] = state

            return self._public_state(state)

    def set_connection_state(self, account_id, connected):
        with self.lock:
            state = self._get(account_id)

            state["connected"] = bool(connected)

            if connected:
                state["last_connection_at"] = utc_now()

            state["updated_at"] = utc_now()

            return self._public_state(state)

    def start_account(self, account_id):
        """
        Start permission is granted only when the account is
        connected and execution has not been disabled.
        """
        with self.lock:
            state = self._get(account_id)

            if not state["connected"]:
                raise RuntimeError(
                    "Cannot start trading while disconnected"
                )

            if not state["execution_enabled"]:
                raise RuntimeError(
                    "Execution has been disabled for this account"
                )

            state["running"] = True
            state["last_started_at"] = utc_now()
            state["updated_at"] = utc_now()

            return self._public_state(state)

    def stop_account(self, account_id):
        with self.lock:
            state = self._get(account_id)

            state["running"] = False
            state["last_stopped_at"] = utc_now()
            state["updated_at"] = utc_now()

            return self._public_state(state)

    def set_entry_block(
        self,
        account_id,
        blocked,
        reason=None
    ):
        """
        Record the risk supervisor's permission to block new entries.

        Blocking new entries does not automatically close
        existing positions.
        """
        with self.lock:
            state = self._get(account_id)

            state["entry_blocked"] = bool(blocked)

            state["entry_block_reason"] = (
                str(reason)
                if blocked and reason is not None
                else None
            )

            state["updated_at"] = utc_now()

            return self._public_state(state)

    def set_execution_enabled(self, account_id, enabled):
        """
        Explicitly enable or disable account execution.

        Disabling execution stops new execution permission.
        It does not itself close open broker positions.
        """
        with self.lock:
            state = self._get(account_id)

            state["execution_enabled"] = bool(enabled)

            if not enabled:
                state["running"] = False

            state["updated_at"] = utc_now()

            return self._public_state(state)

    def can_open_new_position(self, account_id):
        """
        Check account-level permission before the original
        entry engine sends a new order.
        """
        with self.lock:
            state = self._get(account_id)

            return bool(
                state["connected"]
                and state["running"]
                and state["execution_enabled"]
                and not state["entry_blocked"]
            )

    def can_manage_existing_positions(self, account_id):
        """
        Existing positions remain eligible for management even
        when new entries are blocked.

        The account must still have an active broker connection
        for live broker actions.
        """
        with self.lock:
            state = self._get(account_id)

            return bool(
                state["connected"]
                and state["execution_enabled"]
            )

    def get_account(self, account_id):
        with self.lock:
            state = self._get(account_id)
            return self._public_state(state)

    def get_all_accounts(self):
        with self.lock:
            return {
                account_id: self._public_state(state)
                for account_id, state in self.accounts.items()
            }

    def remove_account(self, account_id):
        """
        Remove local registry state only.

        The caller must first handle broker connections,
        active positions and persistent account records.
        """
        account_id = str(account_id)

        with self.lock:
            state = self.accounts.get(account_id)

            if state is None:
                return False

            if state["running"]:
                raise RuntimeError(
                    "Stop the account before removing it"
                )

            del self.accounts[account_id]

            return True

    def _get(self, account_id):
        account_id = str(account_id)

        state = self.accounts.get(account_id)

        if state is None:
            raise KeyError(
                f"Trading account {account_id} is not registered"
            )

        return state

    @staticmethod
    def _public_state(state):
        """
        Never expose passwords, API tokens or private credentials.
        """
        return {
            key: value
            for key, value in state.items()
            if key not in {
                "mt5_password",
                "password",
                "metaapi_token",
                "api_token"
            }
        }
