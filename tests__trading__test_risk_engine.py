from trading.risk_engine import RiskEngine

def test_risk_engine_blocks_drawdown():
 engine=RiskEngine(drawdown_limit=20)
 assert not engine.allow_entry(1000,700,0,100,10,1,0,10)
def test_risk_engine_allows_safe_entry():
 engine=RiskEngine(drawdown_limit=35,max_positions=2,max_cost_ratio=.2)
 assert engine.allow_entry(1000,990,0,100,10,.1,0,2)
