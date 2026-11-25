"""Supervision primitives; restart must be preceded by broker position reconciliation."""
class ProcessSupervisor:
 def __init__(self,terminal_manager,reconcile): self.terminals=terminal_manager; self.reconcile=reconcile
 def ensure_running(self,account_id,profile_dir,config_path):
  if self.terminals.status(account_id)=="RUNNING": return False
  self.reconcile(account_id) # avoid replaying stale commands/orders blindly
  self.terminals.start(account_id,profile_dir,config_path); return True
