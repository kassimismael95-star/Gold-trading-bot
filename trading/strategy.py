"""Conservative signal helpers; no signal is returned with insufficient data."""
def momentum_signal(closes,min_samples=8,min_move=0.0):
 if len(closes)<min_samples: return None
 delta=float(closes[-1])-float(closes[0])
 if abs(delta)<=float(min_move): return None
 return "BUY" if delta>0 else "SELL"
def confirm_signal(primary,confirmations):
 if primary not in {"BUY","SELL"}: return None
 return primary if all(x==primary for x in confirmations) else None
