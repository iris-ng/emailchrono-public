CREATE TABLE IF NOT EXISTS email_text_mappings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  source_email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  source_field TEXT NOT NULL,
  start_offset INTEGER NOT NULL,
  end_offset INTEGER NOT NULL,
  target_email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  mapping_kind TEXT NOT NULL DEFAULT 'manual',
  confidence REAL NOT NULL DEFAULT 1.0,
  note TEXT NOT NULL DEFAULT '',
  snip_id INTEGER REFERENCES email_snips(id) ON DELETE CASCADE,
  part_index INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (end_offset > start_offset),
  CHECK (mapping_kind IN ('exact', 'manual', 'fuzzy'))
);

CREATE INDEX IF NOT EXISTS idx_email_text_mappings_case_source
ON email_text_mappings(case_id, source_email_id, source_field);

CREATE INDEX IF NOT EXISTS idx_email_text_mappings_target
ON email_text_mappings(target_email_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_text_mappings_snip_part
ON email_text_mappings(snip_id, part_index, source_field)
WHERE snip_id IS NOT NULL AND part_index IS NOT NULL;
