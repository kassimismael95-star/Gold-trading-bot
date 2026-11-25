"""Account exposure aggregation helpers."""
def aggregate_exposure(positions):
 return sum(abs(float(p.get("notional",0))) for p in positions)
def account_exposure_ok(positions,equity,max_ratio=3.0):
 equity=float(equity)
 return equity>0 and aggregate_exposure(positions)<=equity*float(max_ratio)
