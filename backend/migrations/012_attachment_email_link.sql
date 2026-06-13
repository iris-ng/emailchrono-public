-- Email attachments that are themselves messages (message/rfc822 parts, embedded
-- .msg, or .eml/.msg file attachments) become first-class timeline rows with
-- source_kind='attached'. This column links such a parsed row back to the raw
-- attachment it was derived from, which is kept as a downloadable attachment.
-- NULL for every other email. ON DELETE SET NULL keeps the parsed row if the raw
-- attachment is ever removed independently of the email cascade.
ALTER TABLE emails ADD COLUMN derived_from_attachment_id INTEGER REFERENCES attachments(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_emails_derived_attachment ON emails(derived_from_attachment_id);
