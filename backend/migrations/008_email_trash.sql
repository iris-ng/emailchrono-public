ALTER TABLE emails ADD COLUMN deleted_at TEXT;

CREATE INDEX IF NOT EXISTS idx_emails_case_deleted_at
ON emails(case_id, deleted_at);
