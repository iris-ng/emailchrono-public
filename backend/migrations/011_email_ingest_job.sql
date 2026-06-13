-- Link each email to the ingest job that created it, so an upload session can be
-- audited end-to-end ("which emails were added in this upload"). NULL for manual
-- entries and any email created before this migration. ON DELETE SET NULL keeps
-- emails if a job row is ever removed independently of the case cascade.
ALTER TABLE emails ADD COLUMN ingest_job_id INTEGER REFERENCES ingest_jobs(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_emails_ingest_job ON emails(ingest_job_id);
