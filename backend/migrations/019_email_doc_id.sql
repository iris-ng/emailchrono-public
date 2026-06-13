-- Stable, human-facing per-email document identifier: a random 5-character
-- alphanumeric code from an unambiguous alphabet (no 0/O/1/I/L). Unique within a
-- case so it can be cited in exports and the chronology; the integer primary key
-- stays the internal identifier for all foreign keys.
--
-- NULLs are distinct in a SQLite UNIQUE index, so the index tolerates the
-- pre-backfill state. Existing rows are assigned a doc_id by a backfill step in
-- db.init_db() that runs after this migration applies.
ALTER TABLE emails ADD COLUMN doc_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_emails_case_doc_id ON emails(case_id, doc_id);
