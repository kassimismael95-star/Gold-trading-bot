
"""Reconcile assigned accounts into isolated MT5 terminal workers."""

import json
import logging
import os
from pathlib import Path

from account_provisioner import provision
from terminal_config import write_config, write_ea_set

log = logging.getLogger(__name__)


class AccountScheduler:
    def __init__(
        self,
        api,
        agent_id,
        workspace,
        terminal_manager,
        terminal_binary,
        ea_source=None,
    ):
        self.api = api
        self.agent_id = agent_id
        self.workspace = Path(workspace).resolve()
        self.terminals = terminal_manager
        self.terminal_binary = terminal_binary
        self.ea_source = ea_source
        self.accounts = {}

    @staticmethod
    def _read_previous(profile_path):
        try:
            return json.loads(
                (profile_path / "account.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _configuration_changed(previous, account):
        fields = (
            "credential_version",
            "ea_token_version",
            "mode",
            "symbol",
            "live_trading_allowed",
        )
        return any(
            previous.get(field) != account.get(field)
            for field in fields
        )

    def refresh(self):
        # If the API request fails, it raises before any terminal is stopped.
        assignments = self.api.accounts(self.agent_id)
        active_ids = set()

        for account in assignments:
            account_id = int(account["id"])
            active_ids.add(account_id)

            profile_path = self.workspace / str(account_id)
            terminal_path = profile_path / "terminal"

            self.terminals.bind(account_id, terminal_path)
            running = self.terminals.status(account_id) == "RUNNING"

            previous = self.accounts.get(account_id)
            if previous is None:
                previous = self._read_previous(profile_path)

            changed = self._configuration_changed(previous, account)
            needs_restart = running and changed

            raw_positions = account.get("open_positions_count")

            try:
                open_positions = (
                    int(raw_positions)
                    if raw_positions is not None
                    else -1
                )
            except (TypeError, ValueError):
                open_positions = -1

            # Do not terminate an EA while it may be managing open positions.
            # Missing telemetry is treated as unknown, never as a flat account.
            if needs_restart and open_positions != 0:
                self.accounts[account_id] = account
                log.warning(
                    "deferred account reconfiguration account_id=%s open_positions=%s",
                    account_id,
                    open_positions,
                )
                continue

            if not account.get("credential_ready"):
                # Never provision a new terminal using revoked credentials.
                # Keep an existing terminal alive unless recent telemetry
                # confirms that there are no open positions.
                if running and open_positions == 0:
                    self.terminals.stop(account_id)
                    self.accounts.pop(account_id, None)
                elif running:
                    self.accounts[account_id] = account
                else:
                    self.accounts.pop(account_id, None)
                continue

            if running and not changed:
                self.accounts[account_id] = account
                continue

            secret = self.api.credentials(self.agent_id, account_id)

            required = ("login", "server", "password", "ea_token")
            if not all(secret.get(key) for key in required):
                raise RuntimeError(
                    "account_credentials_incomplete_refusing_terminal_launch"
                )

            profile = provision(
                self.workspace,
                account_id,
                account,
            )

            terminal_root = self.terminals.launcher.prepare(profile)
            expert_rel = "Experts\\GoldScalper\\GoldScalperEA.ex5"

            if not self.ea_source:
                raise RuntimeError(
                    "EA_SOURCE_DIR is required; refusing to launch without the managed EA"
                )

            from ea_installer import install_ea
            from ea_compiler import compile_ea

            expert_dir = Path(
                install_ea(self.ea_source, terminal_root)
            )

            source = expert_dir / "GoldScalperEA.mq5"
            metaeditor = os.environ.get("METAEDITOR_COMMAND", "")

            if not source.is_file() or not metaeditor:
                raise RuntimeError(
                    "EA source or METAEDITOR_COMMAND missing; refusing to start uncompiled EA"
                )

            compiled = expert_dir / "GoldScalperEA.ex5"
            compiled.unlink(missing_ok=True)

            result = compile_ea(
                metaeditor,
                str(source),
                str(expert_dir / "compile.log"),
            )

            if not result.get("success") or not compiled.is_file():
                raise RuntimeError(
                    "MetaEditor compilation failed; inspect private compile.log"
                )

            parameters = write_ea_set(
                expert_dir,
                self.api.base_url,
                self.agent_id,
                account_id,
                secret["ea_token"],
                account.get("symbol", "AUTO"),
                risk_settings=account.get("risk_settings", {}),
                allow_live_trading=account.get(
                    "live_trading_allowed",
                    False,
                ),
                mode=account.get("mode", "demo"),
            )

            config = write_config(
                terminal_root,
                secret["login"],
                secret["server"],
                account.get("symbol", "AUTO"),
                secret["password"],
                expert_rel,
                parameters,
            )

            try:
                # A changed running terminal is restarted only after the
                # assignment API confirms zero open positions.
                if needs_restart:
                    self.terminals.stop(account_id)

                process = self.terminals.start(
                    account_id,
                    str(terminal_root),
                    str(config),
                )

                self.accounts[account_id] = account

                log.info(
                    "terminal started account_id=%s pid=%s mode=%s",
                    account_id,
                    process.pid,
                    account.get("mode", "demo"),
                )

            finally:
                # Remove the transient file containing the broker password.
                try:
                    Path(config).unlink(missing_ok=True)
                except OSError:
                    log.warning(
                        "could not remove transient terminal config account_id=%s",
                        account_id,
                    )

        # The assignment endpoint retains deleted accounts until recent
        # telemetry confirms that the broker account is flat and connected.
        # Therefore, a successfully returned list may safely release accounts
        # that are no longer assigned.
        for account_id in list(self.accounts):
            if account_id not in active_ids:
                self.terminals.stop(account_id)
                self.accounts.pop(account_id, None)

        return self.accounts
