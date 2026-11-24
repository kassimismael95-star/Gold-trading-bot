# Strategy Preservation

This document defines exactly how the original `app.py` strategy must be preserved.

The original `app.py` is the source of truth for trading behavior.

No replacement strategy engine may silently change trading behavior.

## Preserve exactly

The rebuilt system must preserve:

- `MAX_ALLOWED_SPREAD_PIPS = 35.0`
- `POLL_LATENCY_DELAY = 0.05`
- `BURST_SPACING_DELAY = 0.08`
- `ADD_POSITION_MOVE_USD = 0.15`
- `MULTI_SCALP_COOLDOWN_SECONDS = 3`
- Hard maximum of 18 positions
- SL base of 2.00 USD and TP base of 2.20 USD
- SL range of 1.50–3.00 USD
- TP range of 1.80–3.50 USD
- MetaApi magic `9924102`
- Signature format `BALANCED-SCALP-{position_number} [{key}]`
- Symbol resolver order: requested, `XAUUSDm`, `XAUUSD`, `XAUUSDc`, `XAUUSDr`, `GOLD`
- MicroMomentumTracker rolling 20-tick logic
- Dynamic burst and added-lot tiers
- Dynamic SL/TP formula

## MicroMomentumTracker

The MicroMomentumTracker must preserve:

- Rolling 20 ticks.
- If fewer than 3 ticks, return BUY with confidence 6.
- Weighted recent/full-window/current-minute candle deltas.
- Clamp score between -10 and 10.
- BUY if score >= 0.
- SELL otherwise.

## Dynamic burst

The dynamic burst logic must preserve:

- Burst spacing delay.
- Added-lot tiers.
- Dynamic SL/TP formula.

## Basket close

The basket close logic must preserve:

- Close all basket positions.
- Report close results.
- Update basket state.
- Prevent orphan positions.

## Symbol resolver

The symbol resolver order must preserve:

```text
requested symbol
XAUUSDm
XAUUSD
XAUUSDc
XAUUSDr
GOLD
