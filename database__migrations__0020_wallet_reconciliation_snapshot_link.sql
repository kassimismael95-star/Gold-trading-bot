-- Link reconciliation differences to the exact provider balance snapshot.
ALTER TABLE wallet_reconciliation ADD COLUMN IF NOT EXISTS snapshot_id INTEGER REFERENCES wallet_balance_snapshot(id);
CREATE INDEX IF NOT EXISTS ix_wallet_reconciliation_snapshot_id ON wallet_reconciliation(snapshot_id);
