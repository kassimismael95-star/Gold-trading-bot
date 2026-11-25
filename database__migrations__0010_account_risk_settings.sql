-- Persist validated per-account trading controls.
ALTER TABLE trading_account ADD COLUMN IF NOT EXISTS risk_settings JSONB NOT NULL DEFAULT '{}';
