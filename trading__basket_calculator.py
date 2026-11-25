"""Basket P/L aggregation using broker-reported profit, swap and commission."""
def basket_net_profit(positions):
 return sum(float(p.get("profit",0))+float(p.get("swap",0))+float(p.get("commission",0)) for p in positions)
def target_reached(positions,target): return basket_net_profit(positions)>=float(target)
def loss_limit_reached(positions,limit): return basket_net_profit(positions)<=-abs(float(limit))
