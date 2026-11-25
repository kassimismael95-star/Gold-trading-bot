"""In-memory worker registry; durable assignments should remain in API database."""
import threading
class WorkerRegistry:
 def __init__(self): self._lock=threading.RLock(); self._workers={}
 def register(self,account_id,worker):
  with self._lock:
   if account_id in self._workers: raise RuntimeError("account_worker_already_registered")
   self._workers[account_id]=worker
 def get(self,account_id):
  with self._lock: return self._workers.get(account_id)
 def remove(self,account_id):
  with self._lock: return self._workers.pop(account_id,None)
 def snapshot(self):
  with self._lock: return list(self._workers.keys())
