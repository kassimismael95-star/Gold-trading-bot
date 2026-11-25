"""Spread/commission/slippage estimate normalized to expected move."""
def cost_ratio(spread,commission_equivalent,expected_move):
 if expected_move<=0: return float("inf")
 return (max(0,float(spread))+max(0,float(commission_equivalent)))/float(expected_move)
def acceptable_cost(spread,commission_equivalent,expected_move,max_ratio=0.2):
 return cost_ratio(spread,commission_equivalent,expected_move)<=max_ratio
