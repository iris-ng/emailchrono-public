PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS email_text_mappings_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  source_email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  source_field TEXT NOT NULL,
  start_offset INTEGER NOT NULL,
  end_offset INTEGER NOT NULL,
  target_email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  target_field TEXT NOT NULL DEFAULT 'body',
  target_start_offset INTEGER,
  target_end_offset INTEGER,
  mapping_kind TEXT NOT NULL DEFAULT 'manual',
  confidence REAL NOT NULL DEFAULT 1.0,
  transform TEXT NOT NULL DEFAULT 'identity',
  created_by TEXT NOT NULL DEFAULT 'system',
  stale INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  snip_id INTEGER REFERENCES email_snips(id) ON DELETE CASCADE,
  part_index INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (end_offset > start_offset),
  CHECK (target_start_offset IS NULL OR target_end_offset IS NULL OR target_end_offset >= target_start_offset),
  CHECK (mapping_kind IN ('parsed', 'quoted', 'attached', 'snipped', 'manual', 'self', 'fuzzy'))
);

INSERT INTO email_text_mappings_new
  (id, case_id, source_email_id, source_field, start_offset, end_offset,
   target_email_id, target_field, target_start_offset, target_end_offset,
   mapping_kind, confidence, transform, created_by, stale, note, metadata_json,
   snip_id, part_index, created_at, updated_at)
SELECT
  id,
  case_id,
  source_email_id,
  source_field,
  start_offset,
  end_offset,
  target_email_id,
  'body',
  NULL,
  NULL,
  CASE
    WHEN mapping_kind = 'exact' AND snip_id IS NOT NULL THEN 'snipped'
    WHEN mapping_kind = 'exact' THEN 'parsed'
    WHEN mapping_kind IN ('parsed', 'quoted', 'attached', 'snipped', 'manual', 'self', 'fuzzy') THEN mapping_kind
    ELSE 'manual'
  END,
  confidence,
  'identity',
  'system',
  0,
  note,
  '{}',
  snip_id,
  part_index,
  created_at,
  updated_at
FROM email_text_mappings;

DROP INDEX IF EXISTS idx_email_text_mappings_case_source;
DROP INDEX IF EXISTS idx_email_text_mappings_target;
DROP INDEX IF EXISTS idx_email_text_mappings_snip_part;
DROP TABLE email_text_mappings;
ALTER TABLE email_text_mappings_new RENAME TO email_text_mappings;

CREATE INDEX IF NOT EXISTS idx_email_text_mappings_case_source
ON email_text_mappings(case_id, source_email_id, source_field);

CREATE INDEX IF NOT EXISTS idx_email_text_mappings_target
ON email_text_mappings(target_email_id);

CREATE INDEX IF NOT EXISTS idx_email_text_mappings_case_kind
ON email_text_mappings(case_id, mapping_kind);

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_text_mappings_snip_part
ON email_text_mappings(snip_id, part_index, source_field)
WHERE snip_id IS NOT NULL AND part_index IS NOT NULL;

CREATE TABLE IF NOT EXISTS email_source_field_cache (
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  field TEXT NOT NULL,
  length INTEGER NOT NULL,
  block_json TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (email_id, field)
);

CREATE INDEX IF NOT EXISTS idx_email_source_field_cache_email
ON email_source_field_cache(email_id);

PRAGMA foreign_keys = ON;
