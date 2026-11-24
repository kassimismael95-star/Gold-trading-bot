# Gold Scalper Roadmap

This document defines the remaining build order and milestones.

The goal is to complete the system in a safe, testable order.

## Build order

1. Finish documentation.
2. Finish database models.
3. Finish migrations.
4. Finish authentication.
5. Finish license system.
6. Finish account registry.
7. Finish worker registry.
8. Finish worker capacity.
9. Finish order routing.
10. Finish bot manager.
11. Finish signal engine.
12. Finish risk manager.
13. Finish MT5 client.
14. Finish command executor.
15. Finish worker API.
16. Finish reconciliation.
17. Finish security.
18. Finish tests.
19. Finish deployment.
20. Finish MT5 pilot.
21. Enable live trading only after explicit authorization.

## Milestone 1: Documentation

Complete:

- `README.md`
- `docs/DEPLOYMENT.md`
- `docs/ARCHITECTURE.md`
- `docs/CAPACITY.md`
- `docs/MT5_PILOT_RESULTS.md`
- `docs/SECURITY.md`
- `docs/TESTING.md`
- `docs/OPERATIONS.md`
- `docs/ROADMAP.md`

## Milestone 2: Database

Complete:

- `database/models.py`
- `database/migrations.py`
- `database/seed.py`

## Milestone 3: Authentication

Complete:

- `services/auth_service.py`
- `api/public_api.py`
- `api/admin_api.py`

## Milestone 4: License system

Complete:

- `services/license_service.py`
- License tests.

## Milestone 5: Account registry

Complete:

- `services/account_service.py`
- Account tests.

## Milestone 6: Worker registry

Complete:

- `services/worker_service.py`
- Worker tests.

## Milestone 7: Worker capacity

Complete:

- Worker capacity logic.
- Capacity tests.

## Milestone 8: Order routing

Complete:

- `services/order_service.py`
- Order routing tests.

## Milestone 9: Bot manager

Complete:

- `services/bot_service.py`
- Bot manager tests.

## Milestone 10: Signal engine

Complete:

- `strategy/micro_momentum_tracker.py`
- `strategy/gold_scalper_strategy.py`
- Signal tests.

## Milestone 11: Risk manager

Complete:

- `services/risk_service.py`
- Risk tests.

## Milestone 12: MT5 client

Complete:

- `worker/mt5_client.py`
- MT5 client tests.

## Milestone 13: Command executor

Complete:

- `worker/command_executor.py`
- Command executor tests.

## Milestone 14: Worker API

Complete:

- `worker/worker_api.py`
- Worker API tests.

## Milestone 15: Reconciliation

Complete:

- `services/reconciliation_service.py`
- Reconciliation tests.

## Milestone 16: Security

Complete:

- `docs/SECURITY.md`
- Security tests.

## Milestone 17: Tests

Complete:

- All unit tests.
- All integration tests.
- All security tests.
- All performance tests.
- All reconciliation tests.
- All EA communication tests.
- All MT5 demo-account tests.
- All order-execution tests.
- All close-basket tests.
- All emergency-stop tests.
- All worker-capacity tests.
- All symbol-resolution tests.
- All license tests.
- All admin-control tests.
- All end-to-end tests.

## Milestone 18: Deployment

Complete:

- `Dockerfile`
- `docker-compose.yml`
- `render.yaml`
- `.github/workflows/ci.yml`
- `.github/workflows/deploy-control-plane.yml`
- `.github/workflows/deploy-website.yml`
- `.github/workflows/provision-oracle.yml`

## Milestone 19: MT5 pilot

Complete:

- Oracle x86 micro VM.
- Wine.
- MetaTrader 5.
- Custom MQL5 EA.
- Demo MT5 account.
- EA polling.
- EA reporting.
- Order execution.
- Reconciliation.
- Pilot results.

## Milestone 20: Live trading

Enable live trading only after:

- All tests pass.
- The Render control plane is deployed.
- Supabase is connected.
- The Oracle x86 MT5 pilot is running.
- The EA is installed.
- The EA connects to the control plane.
- A demo MT5 account executes orders correctly.
- Reconciliation works.
- The user explicitly authorizes live execution.

## Live trading

Live trading is enabled in configuration:

```text
ENABLE_LIVE_TRADING=true
