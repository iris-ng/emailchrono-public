-- Remember which local folders were ingested into a case so the user can
-- re-scan ("refresh") a folder later and pull in only newly added files. The
-- per-file content hash (emails.source_sha256) is what actually drives the
-- skip-existing filter; this table just records the folder roots and when each
-- was last scanned.
CREATE TABLE IF NOT EXISTS case_folders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  folder_path TEXT NOT NULL,
  recursive INTEGER NOT NULL DEFAULT 1,
  last_scanned_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(case_id, folder_path)
);
