-- Replace shared-secret identity spoofing with per-agent credential hashes.
ALTER TABLE agent ADD COLUMN IF NOT EXISTS secret_hash VARCHAR(64);
