-- Password reset invalidates all previously issued access and refresh tokens.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0;
