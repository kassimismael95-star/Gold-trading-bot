-- Host resource telemetry used for conservative agent account capacity.
ALTER TABLE agent ADD COLUMN IF NOT EXISTS metrics JSONB NOT NULL DEFAULT '{}';
