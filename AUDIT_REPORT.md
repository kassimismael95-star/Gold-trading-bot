# Audit report — Gold Trading Bot updated development repository

Audit date: 2026-11-25

## Implemented in the repository

### Authentication and security
- Email OTP verification and password reset with expiry, resend cooldown, attempt limits and peppered HMAC OTP storage.
- Access/refresh JWTs, refresh flow, access and refresh logout revocation, persistent JTI blocklist, and session-version invalidation after password reset.
- Database-backed rate limiting for multi-worker production deployments.
- AES-GCM encryption of MT5 passwords and EA tokens with account-specific associated data; legacy ciphertext is upgraded on authenticated retrieval.
- Per-agent secret enrollment/rotation and account-assignment-scoped credential retrieval.
- Admin audit logging for sensitive account, command, licence, subscription and agent actions.
- Explicit production CORS, secret, PostgreSQL and bootstrap-admin validation. Production does not auto-create schema unless explicitly overridden.

### Payments, merchant wallet and subscriptions
- Flutterwave checkout, webhook signature validation, independent provider transaction verification, exact amount/currency/reference/customer checks and provider transaction uniqueness.
- Idempotent webhook processing and internal wallet ledger posting.
- Flutterwave v3 merchant balance snapshots, available/ledger balance observation, reconciliation records and an opt-in periodic PostgreSQL-lock-protected sync loop.
- Refund initiation, pending-review handling for ambiguous provider outcomes, completed refund ledger entries, refund/dispute administration, and full-refund subscription entitlement revocation.
- Payment-linked subscription records, renewal from the later of existing expiry or current time, paid entitlement synchronization, trial rules, VIP assignment, expiry services and admin subscription extension/revocation.
- Customer payment notification email and dashboard polling for updated payment/subscription state.

### EA, trading controls and telemetry
- Account-level validated risk settings, command acknowledgement, START/STOP/CLOSE_ALL/SETTINGS/EMERGENCY_STOP/risk-reset behavior.
- Broker-aware symbol and trade-spec checks, margin-aware lot sizing, stop-distance checks, trend/volatility/spread/candle entry filters, trailing/break-even, basket profit/loss and account drawdown locks.
- Adaptive volume/confidence state persisted per account, reduced after losing streaks and cautiously increased after winning streaks within fixed bounds.
- Optional session and high-impact USD calendar filters; disabled by default.
- Persistent same-bar restart protection and idempotent recent deal-history synchronization for customer trade history.
- EA reports broker connectivity separately from agent status, plus balance/equity/free margin/floating P&L/positions/entry permission.
- Live account creation and EA execution remain operator-gated; default `ALLOW_LIVE_TRADING=false` and EA default is demo-only.

### Oracle / MT5 and multi-account
- Per-account terminal workspaces, credentials, EA token, configuration and logs.
- Customer account removal is soft-delete: new entries are blocked immediately; an assigned EA is retained until a recent connected heartbeat confirms zero positions, then credentials/token are revoked and the worker is detached.
- Agent enrollment, per-agent authentication, account assignment and configurable capacity.
- CPU/memory/disk resource metrics feed a conservative effective capacity capped by admin settings.
- Persistent terminal PID/process-group tracking and recovery after agent process restart; scheduler does not replay market-order commands.
- Linux launch requires a verified Wine/launcher command; EA compilation requires a real MetaEditor installation.
- Credential/token changes trigger safe terminal replacement after replacement config/source validation; revoked credentials stop new entries while open positions remain managed by a running EA.
- Oracle systemd installation/configuration scripts and deployment documentation.

### Database, dashboard and CI
- PostgreSQL migration sequence 0001–0020 covers core models, wallet/payment records, credential vault, OTP, audit/rate limits, subscriptions, session revocation, agent secrets/capacity/metrics, risk settings, telemetry and idempotent deal history.
- Database model package exports, customer/admin APIs, dashboard modules, reconciliation/refund/dispute views and deployment workflows are included.
- Files retain full relative paths inside the `Gold-trading-bot/` repository root.

## Checks run in this build environment

- `python -m compileall -q apps services tests trading` — passed.
- `node --check apps/web/app.js` and `node --check apps/web/admin.js` — passed.
- `bash -n infrastructure/oracle/*.sh` — passed.
- YAML parse of GitHub workflows and `render.yaml` — passed.
- Static Python symbol-table scan — 0 possible undefined globals.
- Dependency-free test subset — 22 passed.
- Full `pytest -q` — could not collect Flask-dependent tests because Flask is not installed in the build environment; dependency installation was unavailable. API/payment/session tests are present for CI but were not executed here.
- PostgreSQL migration integration workflow was authored but not run locally.
- ZIP integrity and extraction check — passed; 237 files are packaged under the exact `Gold-trading-bot/` root with full relative paths.

## Required external verification before live use

This repository is **not certified as 100% production-ready or live-tested**. The following still require real runtime/provider access:

- Full Flask-dependent API/auth/payment/agent test suite in CI.
- Fresh PostgreSQL migration run and safe upgrade/baseline against a backed-up existing database.
- Flutterwave sandbox/merchant checkout, webhook retry/signature, balance permissions, settlement/fee/refund/dispute callbacks and reconciliation.
- Oracle host install, Wine/MT5 terminal login, portable terminal behavior, automatic EA attachment and startup config consumption.
- MetaEditor compilation of all MQL5 sources and validation of economic-calendar API compatibility.
- Broker demo soak tests for entry/exit, slippage, stop/freeze levels, disconnect/reconnect, terminal crash, account reassignment and duplicate-order prevention.
- Independent security review, backup/restore, monitoring and load tests. No profitability, maximum-loss, uptime or 1,000-account capacity guarantee is made.

## Release gates

1. Run complete CI and PostgreSQL migration integration.
2. Complete Flutterwave sandbox tests, including duplicate payments and refunds.
3. Compile EA with MetaEditor and test on broker demo accounts.
4. Verify Oracle provisioning and isolation using at least two independent demo accounts.
5. Complete monitored demo soak, recovery, security and capacity tests.
6. Only then assess a restricted live pilot.
