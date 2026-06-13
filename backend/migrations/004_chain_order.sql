ALTER TABLE emails ADD COLUMN chain_source_id INTEGER;
ALTER TABLE emails ADD COLUMN chain_position INTEGER NOT NULL DEFAULT 0;
ALTER TABLE emails ADD COLUMN manual_chain_order INTEGER;

CREATE INDEX IF NOT EXISTS idx_emails_case_chain_source
ON emails(case_id, chain_source_id, chain_position);

CREATE INDEX IF NOT EXISTS idx_emails_case_manual_chain_order
ON emails(case_id, manual_chain_order);
