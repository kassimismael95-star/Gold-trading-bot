TIERS=[
(4,.01,2,.35),(10,.01,3,.50),(25,.02,5,1),(50,.03,7,2),(100,.04,9,4),
(250,.06,12,8),(500,.10,14,15),(1000,.20,16,30),(2000,.35,18,60),
(5000,.60,18,120),(10000,1.00,18,250),(25000,2.00,18,600),(float("inf"),4.00,18,1500)]
def tier_for_equity(equity):
    for ceiling,lot,count,target in TIERS:
        if equity<ceiling: return {"base_lot":lot,"max_positions":count,"basket_target":target}
    raise AssertionError("unreachable")
def lot_for_position(equity, position_number):
    t=tier_for_equity(equity); lot=t["base_lot"]
    if equity>=25: lot += (max(0,(max(1,position_number)-3)//2))*.01
    return round(lot,2)
def dynamic_targets(confidence, positions, movement):
    sl=2.00; tp=2.20
    if movement>.50: sl*=1.30; tp*=1.30
    elif movement>.25: sl*=1.15; tp*=1.15
    elif movement>.10: sl*=1.05; tp*=1.05
    if confidence>=8: sl*=1.15; tp*=1.15
    elif confidence>=6: sl*=1.08; tp*=1.08
    elif confidence<=2: sl*=.90; tp*=.90
    sl*=1+max(0,positions)*.08; tp*=1+max(0,positions)*.08
    sl=max(1.50,min(3.00,sl)); tp=max(1.80,min(3.50,tp))
    return {"sl_usd":round(sl,2),"tp_usd":round(max(sl,tp),2)}
def entry_cost_is_acceptable(expected_profit, spread_cost, commission, estimated_slippage):
    cost=max(0,spread_cost)+max(0,commission)+max(0,estimated_slippage)
    return expected_profit>0 and cost/expected_profit<=.30
