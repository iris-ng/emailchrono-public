ALTER TABLE emails ADD COLUMN manual_chrono_order INTEGER;

CREATE INDEX IF NOT EXISTS idx_emails_case_manual_chrono_order
ON emails(case_id, manual_chrono_order);
