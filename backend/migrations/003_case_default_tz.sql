-- Per-matter default timezone. Used to interpret dates that have no explicit
-- timezone (e.g. quoted "On ... wrote:" headers) when building the chronology.
ALTER TABLE cases ADD COLUMN default_tz TEXT NOT NULL DEFAULT 'UTC';
