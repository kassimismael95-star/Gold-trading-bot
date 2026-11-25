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
