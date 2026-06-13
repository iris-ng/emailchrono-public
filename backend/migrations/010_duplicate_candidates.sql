CREATE TABLE IF NOT EXISTS email_duplicate_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  email_a_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  email_b_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  score REAL NOT NULL,
  reason_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending',
  canonical_email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
  duplicate_email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  decided_at TEXT,
  CHECK (email_a_id < email_b_id),
  CHECK (status IN ('pending', 'duplicate', 'dissimilar')),
  UNIQUE (case_id, email_a_id, email_b_id)
);

CREATE INDEX IF NOT EXISTS idx_duplicate_candidates_case_status
ON email_duplicate_candidates(case_id, status);

CREATE INDEX IF NOT EXISTS idx_duplicate_candidates_email_a
ON email_duplicate_candidates(email_a_id);

CREATE INDEX IF NOT EXISTS idx_duplicate_candidates_email_b
ON email_duplicate_candidates(email_b_id);
