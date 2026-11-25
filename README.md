# Gold Trading Bot — updated development repository

This repository contains the Gold Scalper Flask API, mobile-responsive web control panel, MQL5 expert advisor, Oracle MT5 agent, PostgreSQL schema migrations, and tests. It is a demo-first development project. **It is not certified as a complete production or profitable live-trading system.** Read `AUDIT_REPORT.md` before deploying.

## Repository layout

- `apps/api/` — authentication, accounts, licences, payments, wallet, dashboard, EA and agent APIs
- `apps/web/` — customer and administrator control UI
- `database/migrations/` — ordered PostgreSQL SQL migrations
- `services/oracle-agent/` — isolated MT5 account provisioning and process supervision
- `infrastructure/oracle/` — host installation and service scripts
- `trading/ea/` — MQL5 EA and integrated strategy/risk/management modules
- `tests/` — API, payment, security, multi-account and trading tests

All files are stored using their complete relative directory paths. Keep that structure when pushing to GitHub.

## Customer lifecycle

1. Register with an email and password of at least 12 characters. In production, SMTP must be configured; the customer verifies the email using a short-lived OTP. OTPs are hashed at rest, expire, have attempt limits and a resend cooldown.
2. Create an MT5 **demo** account. Live accounts are accepted only when the operator explicitly enables `ALLOW_LIVE_TRADING=true` on the API; the default is false. The API encrypts the submitted password using AES-GCM and returns an EA token once. The password is not included in account-list responses or browser localStorage.
3. An administrator assigns `BOSSMODE98` or `BOSSMODE99`; the customer activates the assigned code. `BOSSMODE01D` provides two 24-hour trials, with a 96-hour cooldown after the first trial expires. Paid access is activated only after provider-side payment verification.
4. A customer chooses `PLAN_15D` ($25 / 15 days), `PLAN_33D` ($50 / 33 days), or `PLAN_70D` ($100 / 70 days). Flutterwave transaction verification checks provider status, transaction ID, reference, exact amount, currency, customer and duplicate use before subscription/entitlement activation.
5. Verified payment income is posted idempotently to the internal ledger. Provider merchant balance observations are fetched separately through Flutterwave's v3 balance endpoint and reconciled as snapshots. The internal ledger is not represented as the provider's actual balance.
6. Customer commands include START, STOP, CLOSE_ALL, EMERGENCY_STOP and validated per-account SETTINGS. STOP/CLOSE_ALL/EMERGENCY_STOP stop new entries; the EA continues managing positions already held by the broker. A persisted risk lock requires an administrator reset before new entries can resume.

## Oracle agent and account isolation

- Agents enroll once using the bootstrap `AGENT_SHARED_SECRET`; enrollment returns a unique per-agent secret. The agent stores it in a mode-0600 workspace file or uses `AGENT_SECRET` from its protected environment. On Linux set `MT5_LAUNCH_COMMAND=wine` (or the exact supported wrapper command); MetaEditor requires its own verified `METAEDITOR_COMMAND`.
- Agent API requests use `X-Agent-ID` plus the individual `X-Agent-Secret`. The bootstrap secret is accepted only for enrollment, not ordinary account/credential/command requests.
- Accounts are assigned to one agent and each account gets a separate workspace and portable terminal tree. Customer account removal is soft-delete: new entries stop immediately, and an assigned EA remains to manage open positions until a recent connected heartbeat confirms zero positions; credentials/token are then revoked and the terminal detached.
- Credentials are retrieved only for the authenticated agent to which the account is assigned. Credential and EA-token versions cause the worker to restart the terminal after an update.
- Terminal startup uses a restricted transient configuration file. The agent removes it after startup; test the exact MT5 build and host before using it.
- Worker restart reuses the same account terminal data directory, so broker positions and terminal global variables can be reconciled locally. The EA uses account/magic filtering and a persistent same-bar restart guard to reduce duplicate entries.

## EA controls and protections

The EA includes local tick momentum, closed-candle confirmation, volatility-aware spread filtering, broker symbol/specification checks, margin-fit volume reduction, broker stop-level checks, per-position break-even/trailing management, basket profit/loss controls, account drawdown lock, session filter, optional high-impact USD calendar filter, command acknowledgement and telemetry.

News and session filters are optional and disabled by default. If the news filter is enabled and the terminal calendar data is unavailable, new entries are blocked. Basket targets and lot tiers are configurable/aggressive; they are not a profit guarantee or maximum-loss guarantee. Live account execution remains locked by default.

## Deployment

Use Python 3.11 or later and install `requirements.txt`.

### Development

```bash
python -m venv .venv
# activate the environment
pip install -r requirements.txt
cp .env.example .env
python -m apps.api.app
```

Development startup may create tables with SQLAlchemy `create_all()` for convenience.

### Production

1. Set `APP_ENV=production`, persistent PostgreSQL `DATABASE_URL`, unique 32+ character `APP_SECRET_KEY`, `JWT_SECRET_KEY` and `AGENT_SHARED_SECRET`, explicit non-wildcard `CORS_ORIGINS`, a valid URL-safe base64 32-byte `CREDENTIAL_ENCRYPTION_KEY`, Flutterwave keys/hash/redirect, SMTP settings and bootstrap admin credentials.
2. Apply the numbered SQL migrations in `database/migrations/` to a fresh database in order. For an existing database, inspect and baseline its current schema; **do not replay `0001_initial_schema.sql`**.
3. Keep `AUTO_CREATE_DB=false`. Production startup intentionally does not mutate the schema with `create_all()`.
4. Store secrets in Render environment settings and the Oracle agent's protected environment. Never commit `.env`, `.agent-secret`, MT5 passwords, API keys, terminal config files or database dumps.
5. The periodic merchant-balance loop is opt-in (`ENABLE_BALANCE_SYNC_LOOP=true`) and uses a PostgreSQL advisory lock to avoid duplicate worker syncs. Render free instances can sleep, so hourly balance checks require an always-on service/worker.
6. On the Oracle host, install Python/Wine and a legitimate MT5 terminal/MetaEditor. Copy `infrastructure/oracle/gold-agent.env.example` to `/etc/gold-agent.env`, set real host/API paths and secrets, then run `sudo bash infrastructure/oracle/configure_agent.sh`. The script installs the agent and enables its systemd service; start it only after terminal paths and Wine/MetaEditor commands are verified.
7. Compile the EA, confirm the expected `.ex5` exists, and verify chart attachment and broker login on a demo account before enabling account entries.

## Important endpoints

- `POST /api/auth/register`, `/login`, `/verify-email`, `/verification/resend`, `/password-reset/request`, `/password-reset/confirm`, `/refresh`, `/logout`
- `GET/POST/DELETE /api/accounts`; account-specific commands, credential update/revocation and EA token rotation
- `GET /api/dashboard/summary`, `/payments`, `/trades`
- `GET /api/plans`; `POST /api/payments/flutterwave/initialize`; provider payment and refund webhooks
- `GET /api/wallet/summary`, `/reconciliations`, `/snapshots` and admin `POST /api/wallet/sync`
- `POST /api/admin/vip/assign`, `/vip/revoke`, subscription extend/revoke, payment refund, agent secret rotation/capacity, account reassignment and risk-lock reset
- `POST /api/agent/register` (bootstrap secret only), `/heartbeat`, `/accounts`, account credential retrieval (per-agent secret)
- `GET /api/ea/next`, `/permission`; `POST /api/ea/ack`, `/events`, `/deals/batch` (account EA token)

## Verification status

Python syntax compilation, web JavaScript syntax checks, and the available dependency-free test subset are recorded in `AUDIT_REPORT.md`. The environment used for this package had no package-index network access, so Flask-dependent API tests could not be collected here. MetaEditor, a real Flutterwave merchant account, a live Oracle VM and an MT5 broker demo account were not available for end-to-end validation. No claim is made that these integrations have been live-tested or that trading is profitable.
