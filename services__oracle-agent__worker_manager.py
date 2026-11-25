"""One supervised terminal process handle per account."""
import subprocess, threading
class WorkerManager:
    def __init__(self, launcher): self.launcher=launcher; self._lock=threading.RLock(); self._processes={}
    def start(self, account_id, profile_dir, config_path):
        key=int(account_id)
        with self._lock:
            p=self._processes.get(key)
            if p and p.poll() is None: return p
            p=self.launcher.launch(profile_dir,config_path); self._processes[key]=p; return p
    def stop(self, account_id, timeout=20):
        key=int(account_id)
        with self._lock: p=self._processes.get(key)
        if not p: return
        if p.poll() is None:
            p.terminate()
            try: p.wait(timeout=timeout)
            except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=5)
        with self._lock: self._processes.pop(key,None)
    def status(self, account_id):
        p=self._processes.get(int(account_id)); return "RUNNING" if p and p.poll() is None else "STOPPED"
    def snapshot(self):
        with self._lock: return {k:(p.pid,p.poll()) for k,p in self._processes.items()}
