CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER,
  actor TEXT NOT NULL DEFAULT 'local',
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id INTEGER,
  before_json TEXT,
  after_json TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  prev_hash TEXT,
  event_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_events_case_created
ON audit_events(case_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_audit_events_entity
ON audit_events(entity_type, entity_id);
