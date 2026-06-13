-- Phase 1 of body-content dedup. Persist, per email, a canonical normalized
-- body plus a MinHash signature so near-duplicate bodies can be blocked
-- together (LSH bands are derived from the signature) and scored by estimated
-- Jaccard overlap -- not just exact-hash / 240-char-prefix matching.
--
-- These are a derived cache, like an index. They are intentionally nullable
-- with no backfill here: the duplicate recompute (run at ingest completion and
-- after snip/create, never on read) fills them lazily and recomputes a row's
-- signature only when its normalized body has actually changed. Forward-only,
-- per repo convention -- there is no down-migration.
ALTER TABLE emails ADD COLUMN body_norm TEXT;
ALTER TABLE emails ADD COLUMN body_norm_len INTEGER;
ALTER TABLE emails ADD COLUMN body_minhash TEXT;
