-- Simplified Chinese (CJK) search support, Part B: the ingestion "contains
-- Chinese" checkbox.
--
-- ingest_jobs.contains_cjk records, per batch, that the user ticked the
-- "this batch contains Chinese-language content" box -- kept for provenance and
-- surfaced in the audit trail. cases.has_cjk_content is a sticky per-case
-- roll-up (set to 1 whenever any batch is flagged, never auto-cleared) used to
-- pre-tick the checkbox on subsequent uploads for that case.
--
-- Neither flag drives the FTS5 tokenizer: there is one shared emails_fts table
-- with one tokenizer (trigram, migration 024), correct for CJK regardless of
-- this flag. Both columns default 0, so this is a no-op for existing data.
-- Forward-only, per repo convention -- there is no down-migration.
ALTER TABLE ingest_jobs ADD COLUMN contains_cjk INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cases ADD COLUMN has_cjk_content INTEGER NOT NULL DEFAULT 0;
