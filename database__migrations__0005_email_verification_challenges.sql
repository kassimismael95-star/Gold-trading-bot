-- Apply to an existing PostgreSQL deployment after backing up and checking schema.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS email_challenge (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  purpose VARCHAR(24) NOT NULL,
  salt VARCHAR(64) NOT NULL,
  code_hash VARCHAR(64) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  consumed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_email_challenge_user_id ON email_challenge(user_id);
CREATE INDEX IF NOT EXISTS ix_email_challenge_purpose ON email_challenge(purpose);
