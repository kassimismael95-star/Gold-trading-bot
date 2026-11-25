"""Equity drawdown monitor. This is a trigger, not a guaranteed loss cap."""
def drawdown_percent(initial_equity,current_equity):
 if initial_equity<=0: return 100.0
 return max(0.0,(initial_equity-current_equity)/initial_equity*100.0)
def breaker_triggered(initial_equity,current_equity,limit_percent=35):
 return drawdown_percent(initial_equity,current_equity)>=float(limit_percent)
