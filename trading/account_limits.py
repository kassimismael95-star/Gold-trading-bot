"""Per-account entry guardrails; values must be configured per risk profile."""
def can_open_new_position(open_count,max_positions,equity,free_margin,required_margin):
 return (int(open_count)<int(max_positions) and float(equity)>0 and
         float(free_margin)>0 and float(free_margin)>=float(required_margin)*1.2)
