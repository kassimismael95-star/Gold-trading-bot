# Gold Scalper Control Plane

This is a rebuilt trading-bot control plane that preserves the original Gold Scalper execution behavior while replacing MetaApi with:

- A Render-hosted control plane.
- A durable queue and database.
- Isolated Windows MT5 workers.
- A Bolt website.
- Backend-enforced worker capacity.
- Account-level isolation.
- Live-trading authorization gates.

## Important

This system can place real MT5 orders when live trading is enabled and authorized.

Live trading can lose real money.

Do not enable real-money execution until:

- The full system is deployed.
- All tests pass.
- A demo MT5 account has been tested.
- Execution, recovery, reconciliation, and duplicate-order protection have been verified.
- You explicitly authorize live trading.

This software does not guarantee profit.

## Architecture

```text
Bolt website
    |
Render control plane
    |
Database and durable queue
    |
Isolated Windows MT5 workers
    |
MT5 broker
