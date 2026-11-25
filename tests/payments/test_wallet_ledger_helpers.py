from decimal import Decimal
from trading.broker_calculator import normalize_volume,price_distance_to_money
from trading.lot_calculator import lot_for_risk

def test_volume_rounds_down_to_step():
 assert normalize_volume('0.037','0.01','10','0.01')==Decimal('0.03')
def test_money_from_tick_spec():
 assert price_distance_to_money(1.0,0.1,1.0,0.2)==Decimal('2.0')
def test_lot_calculator_respects_step():
 assert lot_for_risk(1000,1,100,0.01,5,0.01)==Decimal('0.10')
