"""Risk-based volume calculation; caller must supply broker-calculated loss per lot."""
from decimal import Decimal,ROUND_FLOOR
def lot_for_risk(equity,risk_percent,stop_loss_money_per_lot,minimum,maximum,step):
 equity,risk,loss=map(Decimal,map(str,(equity,risk_percent,stop_loss_money_per_lot)))
 if equity<=0 or risk<=0 or risk>5 or loss<=0: raise ValueError("risk_inputs_out_of_safe_range")
 raw=equity*risk/Decimal(100)/loss
 from .broker_calculator import normalize_volume
 return normalize_volume(raw,minimum,maximum,step)
