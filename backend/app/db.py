"""Core data-access plumbing: connections, migrations and shared helpers.

Domain queries now live in app.repos.* (cases, emails, threads, ingest_jobs,
duplicates, attachments, dates, ordering, tags). This module keeps only the
connection lifecycle, schema migration runner, and the small time/JSON helpers
that everything depends on. The json/row helpers are re-exported from
services.text_norm so callers can keep using db.json_loads / db.row_to_dict.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .config import ATTACHMENTS_DIR, DATA_DIR, DB_PATH, MIGRATIONS_DIR, SOURCES_DIR
from .services.text_norm import json_dumps, json_loads, row_to_dict  # noqa: F401 (re-exported)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def email_restore_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_data_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    ensure_data_dirs()
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version TEXT PRIMARY KEY,
              applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for path in sorted(Path(MIGRATIONS_DIR).glob("*.sql")):
            version = path.stem
            if version in applied:
                continue
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, utc_now()),
            )
        # Assign doc_ids to any rows predating the doc_id column. Idempotent and
        # cheap once every row has one (it only scans for NULLs).
        from .services.doc_id import backfill_doc_ids

        backfill_doc_ids(conn)
        # Migrate legacy absolute attachment paths to data-dir-relative so they
        # survive a data-dir move (migration 023). Idempotent.
        from .services.relative_paths import backfill_relative_disk_paths

        backfill_relative_disk_paths(conn)
        conn.commit()
