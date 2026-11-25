-- Consolidated PostgreSQL schema: migrations 0001 through 0021
-- Fresh schema reference only; use numbered migrations for deployments.

-- ===== 0001_initial_schema.sql =====
-- Initial PostgreSQL schema for the original development release.
-- Apply only to a fresh database. Existing installations must baseline their
-- schema after review rather than replaying this file over existing tables.
CREATE TABLE IF NOT EXISTS "user" (
 id SERIAL PRIMARY KEY,
 email VARCHAR(254) NOT NULL UNIQUE,
 password_hash VARCHAR(255) NOT NULL,
 role VARCHAR(20) NOT NULL DEFAULT 'customer',
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_user_email ON "user"(email);

CREATE TABLE IF NOT EXISTS trading_account (
 id SERIAL PRIMARY KEY,
 owner_id INTEGER NOT NULL REFERENCES "user"(id),
 label VARCHAR(80) NOT NULL,
 broker VARCHAR(80) NOT NULL DEFAULT 'Exness',
 login VARCHAR(40) NOT NULL,
 server VARCHAR(120) NOT NULL,
 mode VARCHAR(10) NOT NULL DEFAULT 'demo',
 symbol VARCHAR(40) NOT NULL DEFAULT 'AUTO',
 desired_state VARCHAR(12) NOT NULL DEFAULT 'STOPPED',
 actual_state VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
 agent_id VARCHAR(80),
 ea_token_hash VARCHAR(64),
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_trading_account_owner_id ON trading_account(owner_id);
CREATE INDEX IF NOT EXISTS ix_trading_account_agent_id ON trading_account(agent_id);

CREATE TABLE IF NOT EXISTS agent (
 id SERIAL PRIMARY KEY,
 agent_id VARCHAR(80) NOT NULL UNIQUE,
 hostname VARCHAR(120),
 last_seen TIMESTAMPTZ,
 status VARCHAR(20) DEFAULT 'OFFLINE'
);

CREATE TABLE IF NOT EXISTS command (
 id SERIAL PRIMARY KEY,
 account_id INTEGER NOT NULL REFERENCES trading_account(id),
 command VARCHAR(20) NOT NULL,
 payload JSONB NOT NULL DEFAULT '{}',
 status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 claimed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_command_account_id ON command(account_id);
CREATE INDEX IF NOT EXISTS ix_command_status ON command(status);

CREATE TABLE IF NOT EXISTS account_event (
 id SERIAL PRIMARY KEY,
 account_id INTEGER NOT NULL REFERENCES trading_account(id),
 event_type VARCHAR(40) NOT NULL,
 payload JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_account_event_account_id ON account_event(account_id);

CREATE TABLE IF NOT EXISTS entitlement (
 id SERIAL PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES "user"(id),
 code VARCHAR(30) NOT NULL,
 status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
 expires_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_entitlement_user_id ON entitlement(user_id);

CREATE TABLE IF NOT EXISTS payment (
 id SERIAL PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES "user"(id),
 tx_ref VARCHAR(100) NOT NULL UNIQUE,
 plan_code VARCHAR(30) NOT NULL,
 amount NUMERIC(12,2) NOT NULL,
 currency VARCHAR(3) NOT NULL,
 status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
 provider_id VARCHAR(100),
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_payment_user_id ON payment(user_id);

-- ===== 0002_command_ack_and_account_heartbeat.sql =====
-- PostgreSQL migration for the command acknowledgement and EA heartbeat additions.
-- Back up the database before applying. Fresh databases created from current models
-- already contain these columns; this migration is for databases from the prior ZIP.
ALTER TABLE command ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ NULL;
ALTER TABLE command ADD COLUMN IF NOT EXISTS result JSONB NULL;
ALTER TABLE trading_account ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ NULL;

-- ===== 0003_wallet_ledger.sql =====
-- Wallet accounting tables. Apply after reviewing current schema and backup first.
CREATE TABLE IF NOT EXISTS wallet (
 id SERIAL PRIMARY KEY, owner_user_id INTEGER NULL REFERENCES "user"(id),
 currency VARCHAR(3) NOT NULL DEFAULT 'USD', ledger_balance NUMERIC(14,2) NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS wallet_transaction (
 id SERIAL PRIMARY KEY, wallet_id INTEGER NOT NULL REFERENCES wallet(id),
 payment_id INTEGER NULL UNIQUE REFERENCES payment(id), provider_transaction_id VARCHAR(100) UNIQUE,
 reference VARCHAR(120) NOT NULL UNIQUE, amount NUMERIC(14,2) NOT NULL,
 currency VARCHAR(3) NOT NULL, kind VARCHAR(24) NOT NULL DEFAULT 'PAYMENT',
 status VARCHAR(20) NOT NULL DEFAULT 'POSTED', provider_confirmed_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS wallet_balance_snapshot (
 id SERIAL PRIMARY KEY, currency VARCHAR(3) NOT NULL, provider_balance NUMERIC(14,2) NOT NULL,
 ledger_balance NUMERIC(14,2) NOT NULL, checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 provider VARCHAR(40) NOT NULL DEFAULT 'flutterwave', status VARCHAR(20) NOT NULL DEFAULT 'OBSERVED');
CREATE TABLE IF NOT EXISTS wallet_reconciliation (
 id SERIAL PRIMARY KEY, currency VARCHAR(3) NOT NULL, provider_balance NUMERIC(14,2) NOT NULL,
 ledger_balance NUMERIC(14,2) NOT NULL, difference NUMERIC(14,2) NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'UNMATCHED', note VARCHAR(500),
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payment_webhook_event (
 id SERIAL PRIMARY KEY, event_key VARCHAR(160) NOT NULL UNIQUE, event_type VARCHAR(80) NOT NULL,
 payload_hash VARCHAR(64) NOT NULL, processed BOOLEAN NOT NULL DEFAULT FALSE,
 received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payment_refund (
 id SERIAL PRIMARY KEY, payment_id INTEGER NOT NULL REFERENCES payment(id),
 provider_refund_id VARCHAR(100) UNIQUE, amount NUMERIC(14,2) NOT NULL,
 currency VARCHAR(3) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'REQUESTED',
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payment_dispute (
 id SERIAL PRIMARY KEY, payment_id INTEGER NOT NULL REFERENCES payment(id),
 provider_case_id VARCHAR(100) UNIQUE, status VARCHAR(24) NOT NULL DEFAULT 'OPEN',
 details JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);

ALTER TABLE wallet_balance_snapshot ADD COLUMN IF NOT EXISTS available_balance NUMERIC(14,2) NOT NULL DEFAULT 0;

-- ===== 0004_account_credential_vault.sql =====
-- Account-scoped encrypted MT5 credential storage. Apply once after a backup.
CREATE TABLE IF NOT EXISTS account_credential (
  id SERIAL PRIMARY KEY,
  account_id INTEGER NOT NULL UNIQUE REFERENCES trading_account(id) ON DELETE CASCADE,
  password_ciphertext TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  revoked BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_account_credential_account_id ON account_credential(account_id);
-- Account assignment is nullable in the application model; agents claim accounts
-- under row locks. Existing fixed agent IDs can be reassigned by an administrator.

ALTER TABLE trading_account ADD COLUMN IF NOT EXISTS ea_token_ciphertext TEXT;

-- ===== 0005_email_verification_challenges.sql =====
-- Apply to an existing PostgreSQL deployment after backing up and checking schema.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS email_challenge (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  purpose VARCHAR(24) NOT NULL,
  salt VARCHAR(64) NOT NULL,
  code_hash VARCHAR(64) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  consumed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_email_challenge_user_id ON email_challenge(user_id);
CREATE INDEX IF NOT EXISTS ix_email_challenge_purpose ON email_challenge(purpose);

-- ===== 0006_audit_and_rate_limit.sql =====
-- Audit trail and persistent, multi-worker authentication rate limiting.
-- Apply to PostgreSQL after backup and after migrations 0001-0005.
CREATE TABLE IF NOT EXISTS audit_log (
 id SERIAL PRIMARY KEY, actor_user_id INTEGER NULL REFERENCES "user"(id),
 action VARCHAR(80) NOT NULL, target_type VARCHAR(40), target_id VARCHAR(80),
 details JSONB NOT NULL DEFAULT '{}', remote_addr VARCHAR(64),
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_audit_log_actor_user_id ON audit_log(actor_user_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log(created_at);
CREATE TABLE IF NOT EXISTS rate_limit_record (
 key_hash VARCHAR(64) PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0,
 window_start TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_rate_limit_record_window_start ON rate_limit_record(window_start);

-- ===== 0007_subscription_lifecycle.sql =====
-- Paid subscription records linked one-to-one to verified provider payments.
CREATE TABLE IF NOT EXISTS subscription (
 id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES "user"(id),
 payment_id INTEGER NOT NULL UNIQUE REFERENCES payment(id),
 plan_code VARCHAR(30) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
 starts_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_subscription_user_id ON subscription(user_id);
CREATE INDEX IF NOT EXISTS ix_subscription_status ON subscription(status);
CREATE INDEX IF NOT EXISTS ix_subscription_expires_at ON subscription(expires_at);

-- ===== 0008_session_revocation.sql =====
-- Persist JWT revocations for logout and stolen-token invalidation.
CREATE TABLE IF NOT EXISTS token_blocklist (
 jti VARCHAR(36) PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES "user"(id),
 expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_token_blocklist_user_id ON token_blocklist(user_id);
CREATE INDEX IF NOT EXISTS ix_token_blocklist_expires_at ON token_blocklist(expires_at);

-- ===== 0009_agent_identity_secrets.sql =====
-- Replace shared-secret identity spoofing with per-agent credential hashes.
ALTER TABLE agent ADD COLUMN IF NOT EXISTS secret_hash VARCHAR(64);

-- ===== 0010_account_risk_settings.sql =====
-- Persist validated per-account trading controls.
ALTER TABLE trading_account ADD COLUMN IF NOT EXISTS risk_settings JSONB NOT NULL DEFAULT '{}';

-- ===== 0011_account_telemetry.sql =====
-- Latest per-account MT5 telemetry from authenticated EA heartbeats.
CREATE TABLE IF NOT EXISTS account_telemetry (
 account_id INTEGER PRIMARY KEY REFERENCES trading_account(id) ON DELETE CASCADE,
 balance NUMERIC(14,2) NOT NULL DEFAULT 0, equity NUMERIC(14,2) NOT NULL DEFAULT 0,
 free_margin NUMERIC(14,2) NOT NULL DEFAULT 0, floating_pnl NUMERIC(14,2) NOT NULL DEFAULT 0,
 open_positions_count INTEGER NOT NULL DEFAULT 0, active_symbol VARCHAR(40),
 entries_enabled BOOLEAN NOT NULL DEFAULT FALSE, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);

-- ===== 0012_account_token_version.sql =====
-- Version EA tokens so agents can restart isolated terminals after rotation.
ALTER TABLE trading_account ADD COLUMN IF NOT EXISTS ea_token_version INTEGER NOT NULL DEFAULT 1;

-- ===== 0013_account_event_idempotency.sql =====
-- Unique external event keys prevent duplicate trade-deal history on EA retries.
ALTER TABLE account_event ADD COLUMN IF NOT EXISTS event_key VARCHAR(120);
CREATE UNIQUE INDEX IF NOT EXISTS ix_account_event_event_key ON account_event(event_key);

-- ===== 0014_payment_provider_id_unique.sql =====
-- A provider transaction can belong to only one internal payment.
CREATE UNIQUE INDEX IF NOT EXISTS ix_payment_provider_id ON payment(provider_id);

-- ===== 0015_merchant_wallet_currency_unique.sql =====
-- Prevent concurrent creation of multiple merchant ledger wallets per currency.
CREATE UNIQUE INDEX IF NOT EXISTS uq_merchant_wallet_currency ON wallet(currency) WHERE owner_user_id IS NULL;

-- ===== 0016_user_session_version.sql =====
-- Password reset invalidates all previously issued access and refresh tokens.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0;

-- ===== 0017_agent_capacity.sql =====
-- Agent assignment capacity is a configurable scheduler limit, not a load-test claim.
ALTER TABLE agent ADD COLUMN IF NOT EXISTS capacity INTEGER NOT NULL DEFAULT 20;

-- ===== 0018_agent_resource_metrics.sql =====
-- Host resource telemetry used for conservative agent account capacity.
ALTER TABLE agent ADD COLUMN IF NOT EXISTS metrics JSONB NOT NULL DEFAULT '{}';

-- ===== 0019_account_telemetry_connection.sql =====
-- Track actual MT5 terminal-to-broker connectivity separately from agent health.
ALTER TABLE account_telemetry ADD COLUMN IF NOT EXISTS connected_to_broker BOOLEAN NOT NULL DEFAULT FALSE;

-- ===== 0020_wallet_reconciliation_snapshot_link.sql =====
-- Link reconciliation differences to the exact provider balance snapshot.
ALTER TABLE wallet_reconciliation ADD COLUMN IF NOT EXISTS snapshot_id INTEGER REFERENCES wallet_balance_snapshot(id);
CREATE INDEX IF NOT EXISTS ix_wallet_reconciliation_snapshot_id ON wallet_reconciliation(snapshot_id);

-- ===== 0021_account_soft_delete.sql =====
-- Soft-delete customer accounts so assigned EAs can manage existing positions until flat.
ALTER TABLE trading_account ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS ix_trading_account_deleted_agent ON trading_account(agent_id,is_deleted);
