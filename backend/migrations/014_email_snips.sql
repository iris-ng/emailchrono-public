CREATE TABLE IF NOT EXISTS email_snips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  source_email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  split_offsets_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_snip_parts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snip_id INTEGER NOT NULL REFERENCES email_snips(id) ON DELETE CASCADE,
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  part_index INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(snip_id, email_id),
  UNIQUE(snip_id, part_index)
);

ALTER TABLE emails ADD COLUMN superseded_by_snip_id INTEGER REFERENCES email_snips(id) ON DELETE SET NULL;
ALTER TABLE emails ADD COLUMN superseded_at TEXT;

CREATE INDEX IF NOT EXISTS idx_email_snips_case_source
ON email_snips(case_id, source_email_id);

CREATE INDEX IF NOT EXISTS idx_email_snip_parts_snip
ON email_snip_parts(snip_id, part_index);

CREATE INDEX IF NOT EXISTS idx_emails_case_superseded
ON emails(case_id, superseded_at);
