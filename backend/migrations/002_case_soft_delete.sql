-- Soft delete for cases: a case moved to trash keeps its emails/attachments and
-- can be restored. It is only removed for good via explicit permanent delete.
ALTER TABLE cases ADD COLUMN deleted_at TEXT;

CREATE INDEX IF NOT EXISTS idx_cases_deleted_at ON cases(deleted_at);
