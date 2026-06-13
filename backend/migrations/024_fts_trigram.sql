-- Simplified Chinese (CJK) search support, Part A.
--
-- The original emails_fts used FTS5's default unicode61 tokenizer, which treats
-- a run of Han characters as ONE unsegmented token. Substring queries like 收到
-- against a body containing 我今天收到了邮件 therefore matched nothing, because
-- FTS5 requires whole-token matches and never matches a substring within a
-- token. The trigram tokenizer (SQLite >= 3.34, bundled with Python 3.10+)
-- indexes every 3-character sliding window, giving true substring matching for
-- CJK and all other scripts. Queries of 1-2 characters have no trigram and are
-- handled by a LIKE fallback in repos/emails.py (email_filter_parts).
--
-- FTS5 virtual tables cannot be ALTERed to change the tokenizer, so the table
-- is dropped and rebuilt, then repopulated from the live emails rows. The
-- backfill predicate is deliberately `deleted_at IS NULL` only -- it mirrors the
-- writer invariant (insert_email writes every non-deleted row; delete_email
-- removes the FTS row). Superseded (snip-parent) rows DO stay in FTS and are
-- filtered at query time by `e.superseded_at IS NULL`, so they must NOT be
-- excluded here. Forward-only, per repo convention -- there is no down-migration.
DROP TABLE IF EXISTS emails_fts;
CREATE VIRTUAL TABLE emails_fts USING fts5(subject, body_text, tokenize='trigram');
INSERT INTO emails_fts (rowid, subject, body_text)
SELECT id, subject, body_text FROM emails WHERE deleted_at IS NULL;
