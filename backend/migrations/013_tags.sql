-- User-defined tags, scoped per case. Tags are applied to emails via the
-- email_tags join table. Both cascade on case/email/tag deletion so removing a
-- tag cleanly drops its chips, and trashing a case removes its tag vocabulary.
CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color TEXT NOT NULL DEFAULT '#64748b',
  created_at TEXT NOT NULL,
  UNIQUE(case_id, name)
);

CREATE TABLE IF NOT EXISTS email_tags (
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (email_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_email_tags_tag ON email_tags(tag_id);
