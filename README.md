# Gold Scalper Control Plane

This is the rebuilt control plane for the Gold Scalper trading bot.

It replaces MetaApi with:

- Render control plane.
- Durable PostgreSQL queue and database.
- Isolated Windows MT5 workers.
- Bolt website.

## Architecture

- Render runs the control plane.
- PostgreSQL stores accounts, bots, signals, orders, and worker state.
- Windows workers run MetaTrader 5.
- Workers receive signed commands from the control plane.
- Workers execute MT5 orders.
- Workers report fills, errors, and account state back to the control plane.

## Important

MetaTrader 5 is Windows-only.

The MT5 worker must run on Windows.

Render cannot run MetaTrader 5.

## Live trading

Live trading is enabled in configuration:

```text
ENABLE_LIVE_TRADING=true
