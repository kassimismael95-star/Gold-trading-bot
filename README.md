# BOSSMODE Control Plane

BOSSMODE is a trading-bot control plane built for Render. It manages users, encrypted MT5 account credentials, bot sessions, durable trade commands, worker selection, and command history.

It does **not** execute trades directly. A separate Windows MT5 worker receives approved commands and executes them in MetaTrader 5.

## Current status

This repository is under construction.

The control-plane files are designed to support:

- User accounts and secure sessions
- Encrypted MT5 credentials
- Durable PostgreSQL command queue
- Worker registry and least-loaded worker selection
- Secure worker command routing
- Micro-momentum signal engine
- Risk and basket-position logic
- Reconciliation after reconnects
- Basic automated tests

## Not ready for live trading

Do **not** connect a real trading account or enable live orders yet.

Before live trading, the project still needs:

- Server-side license entitlement verification
- Command ownership verification in the worker
- Correct basket-close command handling
- Persistent momentum tracking across ticks
- Worker command-result updates in the database
- End-to-end tests using a demo MT5 account
- Security review of credentials, sessions, and worker access

## Architecture

```text
Bolt website
→ Render control plane
→ PostgreSQL command queue
→ Windows MT5 worker
→ MetaTrader 5
→ Broker
