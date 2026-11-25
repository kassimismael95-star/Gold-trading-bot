-- Version EA tokens so agents can restart isolated terminals after rotation.
ALTER TABLE trading_account ADD COLUMN IF NOT EXISTS ea_token_version INTEGER NOT NULL DEFAULT 1;
