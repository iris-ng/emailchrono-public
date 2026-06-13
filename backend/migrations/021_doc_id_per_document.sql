-- doc_id now identifies a *document* (one uploaded file, or one manually-created
-- email), not each card. All cards derived from the same uploaded file -- the
-- standalone plus its quoted children and attached emails at every depth, and any
-- later snips/selections off them -- share that one doc_id, denormalized onto each
-- emails row so the chronology/export read path is unchanged.
--
-- This means many rows in a case now share a doc_id, so the previous
-- UNIQUE(case_id, doc_id) index from migration 019 must be dropped; per-document
-- uniqueness is guaranteed by allocate_doc_id() scanning existing emails.doc_id.
DROP INDEX IF EXISTS idx_emails_case_doc_id;
CREATE INDEX IF NOT EXISTS idx_emails_case_doc_id ON emails(case_id, doc_id);

-- Canonical owner of an uploaded file's doc_id (also lets the ingest/job UI label
-- each file with its document id).
ALTER TABLE ingest_files ADD COLUMN doc_id TEXT;
