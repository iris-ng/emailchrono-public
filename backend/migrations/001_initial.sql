CREATE TABLE IF NOT EXISTS cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  source_file TEXT,
  source_file_display TEXT NOT NULL,
  message_id TEXT,
  in_reply_to TEXT,
  references_json TEXT NOT NULL DEFAULT '[]',
  from_addr TEXT NOT NULL DEFAULT '',
  to_json TEXT NOT NULL DEFAULT '[]',
  cc_json TEXT NOT NULL DEFAULT '[]',
  date_utc TEXT,
  date_raw TEXT,
  subject TEXT NOT NULL DEFAULT '',
  body_text TEXT NOT NULL DEFAULT '',
  body_html_raw TEXT NOT NULL DEFAULT '',
  body_html_sanitized TEXT NOT NULL DEFAULT '',
  body_format TEXT NOT NULL DEFAULT 'text',
  thread_id TEXT,
  parse_confidence TEXT NOT NULL DEFAULT 'low',
  source_kind TEXT NOT NULL DEFAULT 'standalone',
  parent_email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
  user_edited INTEGER NOT NULL DEFAULT 0,
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  mime TEXT NOT NULL DEFAULT 'application/octet-stream',
  size INTEGER NOT NULL DEFAULT 0,
  disk_path TEXT NOT NULL,
  content_id TEXT,
  is_inline INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_flags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  flag TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  total_files INTEGER NOT NULL DEFAULT 0,
  processed_files INTEGER NOT NULL DEFAULT 0,
  failed_files INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  error_json TEXT
);

CREATE TABLE IF NOT EXISTS ingest_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES ingest_jobs(id) ON DELETE CASCADE,
  source_file_display TEXT NOT NULL,
  status TEXT NOT NULL,
  email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
  error TEXT,
  warning_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts
USING fts5(subject, body_text);

CREATE TABLE IF NOT EXISTS edits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emails_case_date ON emails(case_id, date_utc);
CREATE INDEX IF NOT EXISTS idx_emails_case_thread ON emails(case_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails(message_id);
CREATE INDEX IF NOT EXISTS idx_ingest_files_job_status ON ingest_files(job_id, status);
CREATE INDEX IF NOT EXISTS idx_email_flags_email_flag ON email_flags(email_id, flag);
