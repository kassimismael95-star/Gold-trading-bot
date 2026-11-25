from trading.risk import tier_for_equity,lot_for_position,dynamic_targets,entry_cost_is_acceptable

def test_equity_tiers():
    assert tier_for_equity(3)["base_lot"]==.01
    assert tier_for_equity(1000)["max_positions"]==18
    assert tier_for_equity(25000)["base_lot"]==4.0

def test_position_lot_increment():
    assert lot_for_position(25,3)==.03
    assert lot_for_position(25,5)==.04

def test_targets_clamped():
    t=dynamic_targets(10,0,.8)
    assert 1.5<=t["sl_usd"]<=3.0
    assert t["tp_usd"]>=t["sl_usd"]

def test_dynamic_cost_gate():
    assert entry_cost_is_acceptable(10,1,0,1)
    assert not entry_cost_is_acceptable(2,1,1,1)
