-- Persist JWT revocations for logout and stolen-token invalidation.
CREATE TABLE IF NOT EXISTS token_blocklist (
 jti VARCHAR(36) PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES "user"(id),
 expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_token_blocklist_user_id ON token_blocklist(user_id);
CREATE INDEX IF NOT EXISTS ix_token_blocklist_expires_at ON token_blocklist(expires_at);
