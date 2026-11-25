-- Unique external event keys prevent duplicate trade-deal history on EA retries.
ALTER TABLE account_event ADD COLUMN IF NOT EXISTS event_key VARCHAR(120);
CREATE UNIQUE INDEX IF NOT EXISTS ix_account_event_event_key ON account_event(event_key);
