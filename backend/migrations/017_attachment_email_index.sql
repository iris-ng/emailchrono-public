-- attachments are looked up by their owning email in attachments_for_emails, the
-- ingest map's per-row attachment_summary, and FK cascade deletes, but the table
-- only had its primary key on id. Index the foreign key so those lookups and the
-- ON DELETE CASCADE from emails stop scanning the whole table.
CREATE INDEX IF NOT EXISTS idx_attachments_email ON attachments(email_id);
