"""Central Python risk policy; mirror tested constants/algorithms in MQL5."""
from .drawdown_monitor import breaker_triggered
from .execution_cost import acceptable_cost
from .account_limits import can_open_new_position
class RiskEngine:
 def __init__(self,drawdown_limit=35,max_positions=3,max_cost_ratio=.2):
  self.drawdown_limit=float(drawdown_limit); self.max_positions=int(max_positions); self.max_cost_ratio=float(max_cost_ratio)
 def allow_entry(self,initial_equity,equity,open_count,free_margin,required_margin,spread,commission,expected_move):
  return (not breaker_triggered(initial_equity,equity,self.drawdown_limit) and
   can_open_new_position(open_count,self.max_positions,equity,free_margin,required_margin) and
   acceptable_cost(spread,commission,expected_move,self.max_cost_ratio))
