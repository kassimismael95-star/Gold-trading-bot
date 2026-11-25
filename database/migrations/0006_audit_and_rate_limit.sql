-- Audit trail and persistent, multi-worker authentication rate limiting.
-- Apply to PostgreSQL after backup and after migrations 0001-0005.
CREATE TABLE IF NOT EXISTS audit_log (
 id SERIAL PRIMARY KEY, actor_user_id INTEGER NULL REFERENCES "user"(id),
 action VARCHAR(80) NOT NULL, target_type VARCHAR(40), target_id VARCHAR(80),
 details JSONB NOT NULL DEFAULT '{}', remote_addr VARCHAR(64),
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_audit_log_actor_user_id ON audit_log(actor_user_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log(created_at);
CREATE TABLE IF NOT EXISTS rate_limit_record (
 key_hash VARCHAR(64) PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0,
 window_start TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_rate_limit_record_window_start ON rate_limit_record(window_start);
