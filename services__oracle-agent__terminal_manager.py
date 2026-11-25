"""Per-account terminal process tracking that survives agent process restarts."""
import os
import signal
import threading
import time
from pathlib import Path

class ExternalProcess:
    def __init__(self,pid): self.pid=int(pid)
    def poll(self): return None if TerminalManager.pid_alive(self.pid) else 1

class TerminalManager:
    def __init__(self,launcher):
        self.launcher=launcher; self._lock=threading.RLock(); self._processes={}; self._pid_paths={}

    @staticmethod
    def pid_alive(pid):
        if pid<=1:return False
        if not os.path.isdir("/proc"):
            try:os.kill(pid,0);return True
            except (OSError,AttributeError):return False
        # The Wine launcher can exit while its MT5 child remains in the same
        # process group. Search the group so agent restarts never spawn a second
        # terminal for an account that is already running.
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():continue
                proc_id=int(entry)
                try:
                    stat=Path(f"/proc/{proc_id}/stat").read_text().split()
                    process_group=int(stat[4])
                    if process_group!=pid:continue
                    cmd=Path(f"/proc/{proc_id}/cmdline").read_bytes().replace(b"\x00",b" ").lower()
                    if b"terminal64.exe" in cmd or b"terminal.exe" in cmd:return True
                except (OSError,ValueError,IndexError):continue
        except (OSError,AttributeError):pass
        return False

    def bind(self,account_id,profile_dir):
        self._pid_paths[account_id]=self._pid_path(profile_dir)

    def _pid_path(self,profile_dir):
        return Path(profile_dir).resolve()/".gold-agent.pid"

    def start(self,account_id,profile_dir,config_path):
        with self._lock:
            p=self._processes.get(account_id)
            if p and p.poll() is None:return p
            pid_path=self._pid_path(profile_dir); self._pid_paths[account_id]=pid_path
            if pid_path.is_file():
                try: pid=int(pid_path.read_text().strip())
                except (OSError,ValueError): pid=0
                if self.pid_alive(pid):
                    p=ExternalProcess(pid); self._processes[account_id]=p; return p
                pid_path.unlink(missing_ok=True)
            p=self.launcher.launch(profile_dir,config_path)
            pid_path.write_text(str(p.pid)+"\n"); os.chmod(pid_path,0o600)
            self._processes[account_id]=p
            return p

    def stop(self,account_id,timeout=15):
        with self._lock:
            p=self._processes.get(account_id); pid_path=self._pid_paths.get(account_id)
            if pid_path is None and p:
                pid_path=Path(getattr(p,"cwd", "."))/".gold-agent.pid"
            pid=0
            if p:
                pid=int(p.pid)
            elif pid_path and pid_path.is_file():
                try:pid=int(pid_path.read_text().strip())
                except (OSError,ValueError):pid=0
            if pid and self.pid_alive(pid):
                try:os.killpg(pid,signal.SIGTERM)
                except (OSError,AttributeError):
                    try:os.kill(pid,signal.SIGTERM)
                    except (OSError,AttributeError):pass
                deadline=time.time()+timeout
                while time.time()<deadline and self.pid_alive(pid):time.sleep(0.25)
                if self.pid_alive(pid):
                    try:os.killpg(pid,signal.SIGKILL)
                    except (OSError,AttributeError):
                        try:os.kill(pid,signal.SIGKILL)
                        except (OSError,AttributeError):pass
            if p and hasattr(p,"wait"):
                try:p.wait(timeout=2)
                except Exception:pass
            if pid_path:pid_path.unlink(missing_ok=True)
            self._processes.pop(account_id,None); self._pid_paths.pop(account_id,None)

    def status(self,account_id):
        with self._lock:
            p=self._processes.get(account_id)
            if p and p.poll() is None:return "RUNNING"
            pid_path=self._pid_paths.get(account_id)
            if pid_path is None:return "STOPPED"
            try:pid=int(pid_path.read_text().strip())
            except (OSError,ValueError):return "STOPPED"
            return "RUNNING" if self.pid_alive(pid) else "STOPPED"
