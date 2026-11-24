# Gold Balanced Multi-Position Scalper Control Plane

This project preserves the original **Gold Balanced Multi-Position Scalper** trading style while adding a durable cloud control plane, isolated Windows MT5 workers, secure credentials, worker capacity limits, and execution reconciliation.

The original strategy, execution rules, lot sizing, stop-loss/take-profit formula, basket behavior, and bot signature remain unchanged.

## Original Trading Style

The system preserves the original balanced multi-position scalping style.

### Core settings

```text
MAX_ALLOWED_SPREAD_PIPS = 35.0
POLL_LATENCY_DELAY = 0.05
BURST_SPACING_DELAY = 0.08
ADD_POSITION_MOVE_USD = 0.15
MULTI_SCALP_COOLDOWN_SECONDS = 3
MAX_POSITIONS_HARD_LIMIT = 18
