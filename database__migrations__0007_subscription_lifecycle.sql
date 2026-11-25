-- Paid subscription records linked one-to-one to verified provider payments.
CREATE TABLE IF NOT EXISTS subscription (
 id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES "user"(id),
 payment_id INTEGER NOT NULL UNIQUE REFERENCES payment(id),
 plan_code VARCHAR(30) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
 starts_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_subscription_user_id ON subscription(user_id);
CREATE INDEX IF NOT EXISTS ix_subscription_status ON subscription(status);
CREATE INDEX IF NOT EXISTS ix_subscription_expires_at ON subscription(expires_at);
