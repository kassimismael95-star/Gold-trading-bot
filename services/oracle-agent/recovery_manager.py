"""Reconcile assigned account workers without replaying market orders."""
class RecoveryManager:
    def reconcile(self,scheduler):
        # AccountScheduler checks persistent terminal PID records, account/token
        # versions, and starts only missing/stopped terminals. The EA then reads
        # broker-held positions and persisted terminal state before considering
        # a new entry; this service never replays an order command.
        accounts=scheduler.refresh()
        running=sum(1 for account_id in accounts if scheduler.terminals.status(account_id)=="RUNNING")
        return {"reconciled":True,"assigned_accounts":len(accounts),"running_terminals":running}
