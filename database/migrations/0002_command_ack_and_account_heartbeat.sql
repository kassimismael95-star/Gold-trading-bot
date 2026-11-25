-- PostgreSQL migration for the command acknowledgement and EA heartbeat additions.
-- Back up the database before applying. Fresh databases created from current models
-- already contain these columns; this migration is for databases from the prior ZIP.
ALTER TABLE command ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ NULL;
ALTER TABLE command ADD COLUMN IF NOT EXISTS result JSONB NULL;
ALTER TABLE trading_account ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ NULL;
