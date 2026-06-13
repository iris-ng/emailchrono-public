-- Stable, opaque public identifier for cases, used in URLs (/cases/<public_id>)
-- so bookmarked/shared links survive database rebuilds, restores and merges.
-- The integer primary key stays the internal identifier for all foreign keys.
ALTER TABLE cases ADD COLUMN public_id TEXT;

-- Backfill existing rows with a random 32-char hex identifier (UUIDv4-like).
UPDATE cases SET public_id = lower(hex(randomblob(16))) WHERE public_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_cases_public_id ON cases(public_id);
