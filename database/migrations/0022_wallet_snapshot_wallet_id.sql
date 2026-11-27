-- Associate each provider balance snapshot with its merchant wallet.
-- Existing snapshots are backfilled before the column becomes mandatory.

ALTER TABLE wallet_balance_snapshot
    ADD COLUMN IF NOT EXISTS wallet_id INTEGER
    REFERENCES wallet(id);

-- Ensure a merchant wallet exists for every currency in historical snapshots.
INSERT INTO wallet (
    owner_user_id,
    currency,
    ledger_balance
)
SELECT DISTINCT
    NULL,
    snapshot.currency,
    0
FROM wallet_balance_snapshot AS snapshot
WHERE NOT EXISTS (
    SELECT 1
    FROM wallet AS existing
    WHERE existing.owner_user_id IS NULL
      AND existing.currency = snapshot.currency
)
ON CONFLICT DO NOTHING;

-- Link historical snapshots to the merchant wallet of the same currency.
UPDATE wallet_balance_snapshot AS snapshot
SET wallet_id = wallet.id
FROM wallet
WHERE wallet.owner_user_id IS NULL
  AND wallet.currency = snapshot.currency
  AND snapshot.wallet_id IS NULL;

-- Every snapshot must now belong to a wallet.
ALTER TABLE wallet_balance_snapshot
    ALTER COLUMN wallet_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_wallet_balance_snapshot_wallet_id
    ON wallet_balance_snapshot(wallet_id);
