"""Oracle agent: heartbeat, fetch assigned accounts, provision and supervise MT5."""
import os, socket, time, logging
from config import Config
from api_client import APIClient
from terminal_launcher import TerminalLauncher
from terminal_manager import TerminalManager
from account_scheduler import AccountScheduler
from health_monitor import HealthMonitor
from recovery_manager import RecoveryManager

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("gold-agent")

def main():
    cfg=Config.validate()
    agent_id=cfg.agent_id or socket.gethostname()
    api=APIClient(cfg.api_base_url,cfg.secret)
    api.ensure_agent_secret(agent_id,cfg.workspace,cfg.secret,cfg.agent_secret)
    install_root=os.environ.get("MT5_INSTALL_DIR","")
    if not install_root:
        raise RuntimeError("MT5_INSTALL_DIR must point to a verified MT5 installation folder")
    ea_source=os.environ.get("EA_SOURCE_DIR","")
    if not ea_source:
        raise RuntimeError("EA_SOURCE_DIR must point to the checked-out trading/ea source folder")
    if not os.environ.get("METAEDITOR_COMMAND",""):
        raise RuntimeError("METAEDITOR_COMMAND must invoke MetaEditor (for example through Wine on Linux)")
    terminals=TerminalManager(TerminalLauncher(install_root,os.environ.get("MT5_LAUNCH_COMMAND","")))
    scheduler=AccountScheduler(api,agent_id,cfg.workspace,terminals,install_root,ea_source)
    health=HealthMonitor(); recovery=RecoveryManager()
    interval=cfg.poll_seconds
    while True:
        try:
            metrics=health.check()
            api.heartbeat(agent_id,socket.gethostname(),metrics)
            recovery.reconcile(scheduler)
        except Exception:
            log.exception("agent reconciliation failed; will retry")
        time.sleep(interval)

if __name__=="__main__": main()
