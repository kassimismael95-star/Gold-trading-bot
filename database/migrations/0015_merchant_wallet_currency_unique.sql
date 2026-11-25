-- Prevent concurrent creation of multiple merchant ledger wallets per currency.
CREATE UNIQUE INDEX IF NOT EXISTS uq_merchant_wallet_currency ON wallet(currency) WHERE owner_user_id IS NULL;
