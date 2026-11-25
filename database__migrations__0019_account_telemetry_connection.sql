-- Track actual MT5 terminal-to-broker connectivity separately from agent health.
ALTER TABLE account_telemetry ADD COLUMN IF NOT EXISTS connected_to_broker BOOLEAN NOT NULL DEFAULT FALSE;
