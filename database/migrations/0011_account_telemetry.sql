-- Latest per-account MT5 telemetry from authenticated EA heartbeats.
CREATE TABLE IF NOT EXISTS account_telemetry (
 account_id INTEGER PRIMARY KEY REFERENCES trading_account(id) ON DELETE CASCADE,
 balance NUMERIC(14,2) NOT NULL DEFAULT 0, equity NUMERIC(14,2) NOT NULL DEFAULT 0,
 free_margin NUMERIC(14,2) NOT NULL DEFAULT 0, floating_pnl NUMERIC(14,2) NOT NULL DEFAULT 0,
 open_positions_count INTEGER NOT NULL DEFAULT 0, active_symbol VARCHAR(40),
 entries_enabled BOOLEAN NOT NULL DEFAULT FALSE, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP);
