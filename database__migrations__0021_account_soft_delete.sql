-- Soft-delete customer accounts so assigned EAs can manage existing positions until flat.
ALTER TABLE trading_account ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS ix_trading_account_deleted_agent ON trading_account(agent_id,is_deleted);
