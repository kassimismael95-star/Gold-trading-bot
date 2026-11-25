-- Agent assignment capacity is a configurable scheduler limit, not a load-test claim.
ALTER TABLE agent ADD COLUMN IF NOT EXISTS capacity INTEGER NOT NULL DEFAULT 20;
