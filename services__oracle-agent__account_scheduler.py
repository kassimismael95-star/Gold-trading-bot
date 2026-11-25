"""Reconcile assigned accounts into isolated MT5 terminal workers."""
import logging, os, json
from pathlib import Path
from account_provisioner import provision
from terminal_config import write_config, write_ea_set

log=logging.getLogger(__name__)

class AccountScheduler:
    def __init__(self, api, agent_id, workspace, terminal_manager, terminal_binary, ea_source=None):
        self.api=api; self.agent_id=agent_id; self.workspace=Path(workspace)
        self.terminals=terminal_manager; self.terminal_binary=terminal_binary; self.ea_source=ea_source
        self.accounts={}

    def refresh(self):
        assignments=self.api.accounts(self.agent_id)
        active_ids=set()
        for account in assignments:
            account_id=int(account["id"]); active_ids.add(account_id)
            profile_path=self.workspace/str(account_id)
            terminal_path=profile_path/"terminal"
            self.terminals.bind(account_id,terminal_path)
            running=self.terminals.status(account_id)=="RUNNING"
            previous=self.accounts.get(account_id)
            if previous is None:
                try: previous=json.loads((profile_path/"account.json").read_text(encoding="utf-8"))
                except (OSError,ValueError): previous={}
            changed=(previous.get("credential_version")!=account.get("credential_version") or
                     previous.get("ea_token_version")!=account.get("ea_token_version"))
            if running and not changed:
                self.accounts[account_id]=account; continue
            needs_restart=running and changed
            if not account.get("credential_ready"):
                # Keep a running terminal alive to manage broker-held positions;
                # account permission is stopped and a revoked credential is never
                # used to provision a replacement terminal.
                if running: self.accounts[account_id]=account
                else: self.accounts.pop(account_id,None)
                continue
            secret=self.api.credentials(self.agent_id,account_id)
            if not all(secret.get(k) for k in ("login","server","password","ea_token")):
                raise RuntimeError("account_credentials_incomplete; refusing to launch terminal")
            # Account-specific directory and restrictive permissions.
            profile=provision(self.workspace,account_id,account)
            terminal_root=self.terminals.launcher.prepare(profile)
            expert_rel="Experts\\GoldScalper\\GoldScalperEA.ex5"
            parameters=None
            if self.ea_source:
                from ea_installer import install_ea
                from ea_compiler import compile_ea
                expert_dir=Path(install_ea(self.ea_source,terminal_root))
                source=expert_dir/"GoldScalperEA.mq5"
                metaeditor=os.environ.get("METAEDITOR_COMMAND","")
                if not source.is_file() or not metaeditor:
                    raise RuntimeError("EA source or METAEDITOR_COMMAND missing; refusing to start uncompiled EA")
                compiled=expert_dir/"GoldScalperEA.ex5"
                compiled.unlink(missing_ok=True)
                result=compile_ea(metaeditor,str(source),str(expert_dir/"compile.log"))
                if not result["success"] or not compiled.is_file():
                    raise RuntimeError("MetaEditor compilation failed; inspect private compile.log")
                parameters=write_ea_set(expert_dir,self.api.base_url,self.agent_id,account_id,
                    secret["ea_token"],account.get("symbol","AUTO"),risk_settings=account.get("risk_settings",{}),allow_live_trading=account.get("live_trading_allowed",False))
            # Credentials are used to create a mode-0600 transient config. Do not log it.
            config=write_config(terminal_root,secret["login"],secret["server"],account.get("symbol","AUTO"),
                secret["password"],expert_rel if parameters else None,parameters)
            try:
                # Keep the old terminal alive until replacement credentials and
                # the new EA have passed validation/compilation. The API has
                # already stopped new entries for credential/token rotations.
                if needs_restart:
                    self.terminals.stop(account_id)
                proc=self.terminals.start(account_id,str(terminal_root),str(config))
                self.accounts[account_id]=account
                log.info("terminal started account_id=%s pid=%s",account_id,proc.pid)
            finally:
                # Remove transient credential file after terminal has consumed it.
                try: Path(config).unlink(missing_ok=True)
                except OSError: log.warning("could not remove transient terminal config for account_id=%s",account_id)
        # Do not stop assigned terminals simply because an API poll temporarily failed;
        # the API client raises on errors and this section only runs on a valid list.
        for account_id in list(self.accounts):
            if account_id not in active_ids:
                self.terminals.stop(account_id)
                self.accounts.pop(account_id,None)
        return self.accounts
