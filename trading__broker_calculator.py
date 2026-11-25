"""Broker-symbol-aware price/volume normalization helpers."""
from decimal import Decimal,ROUND_FLOOR

def normalize_volume(requested,minimum,maximum,step):
 requested,minimum,maximum,step=map(Decimal,map(str,(requested,minimum,maximum,step)))
 if step<=0 or minimum<=0 or maximum<minimum: raise ValueError("invalid_broker_volume_spec")
 value=max(minimum,min(maximum,requested)); units=((value-minimum)/step).to_integral_value(rounding=ROUND_FLOOR)
 return minimum+units*step

def price_distance_to_money(distance,tick_size,tick_value,volume):
 d,tv,v=map(Decimal,map(str,(distance,tick_value,volume))); ts=Decimal(str(tick_size))
 if ts<=0: raise ValueError("invalid_tick_size")
 return abs(d/ts*tv*v)
