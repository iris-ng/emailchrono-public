-- Capture Outlook/Exchange conversation grouping so .msg (and Outlook-origin
-- .eml) mail threads even when it carries no RFC References chain.
--
-- conversation_index is the base64 PR_CONVERSATION_INDEX / Thread-Index value:
-- a 22-byte header (reserved byte + 5-byte FILETIME + 16-byte GUID) shared by
-- every message in a conversation, then a 5-byte block appended per reply. The
-- header identifies the conversation independently of Message-ID/References, so
-- recompute_case_threads can key a thread by it before falling back to subject.
-- conversation_topic is the client-stripped thread subject (PR_CONVERSATION_TOPIC
-- / Thread-Topic), a stable subject that does not drift as the line is edited.
--
-- Both are nullable and only populated for new ingests; existing rows stay NULL
-- and thread exactly as before, so no backfill is needed. Forward-only, per repo
-- convention -- there is no down-migration.
ALTER TABLE emails ADD COLUMN conversation_index TEXT;
ALTER TABLE emails ADD COLUMN conversation_topic TEXT;
