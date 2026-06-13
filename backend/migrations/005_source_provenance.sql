ALTER TABLE emails ADD COLUMN source_import_mode TEXT NOT NULL DEFAULT 'upload';
ALTER TABLE emails ADD COLUMN source_openable INTEGER NOT NULL DEFAULT 0;
ALTER TABLE emails ADD COLUMN source_size INTEGER;
ALTER TABLE emails ADD COLUMN source_mtime TEXT;
ALTER TABLE emails ADD COLUMN source_sha256 TEXT;

ALTER TABLE ingest_files ADD COLUMN source_import_mode TEXT NOT NULL DEFAULT 'upload';
ALTER TABLE ingest_files ADD COLUMN source_size INTEGER;
ALTER TABLE ingest_files ADD COLUMN source_mtime TEXT;
ALTER TABLE ingest_files ADD COLUMN source_sha256 TEXT;
