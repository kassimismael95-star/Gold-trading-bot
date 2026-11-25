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
