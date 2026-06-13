"""One-way backfill: rewrite absolute attachment disk_paths to data-dir-relative.

Historically ``persist_attachments`` stored ``str(path)`` -- an absolute path
under ``ATTACHMENTS_DIR``. That breaks the moment the data dir moves (or the
project is restored on another machine). Going forward attachments store a path
relative to ``ATTACHMENTS_DIR`` (``"<email_id>/<index>-<name>"``); this backfill
migrates legacy rows the first time the app starts after migration 023.

Idempotent: rows already storing a relative path are left untouched, so it is
safe to run on every startup (it only rewrites values that resolve under the
current ATTACHMENTS_DIR). Mirrors the ``backfill_doc_ids`` pattern.
"""

import sqlite3
from pathlib import Path, PurePath

from ..config import ATTACHMENTS_DIR


def _is_absolute(value: str) -> bool:
    # Accept both POSIX and Windows absolute forms regardless of host, so a
    # bundle authored on one OS backfills cleanly on another.
    return PurePath(value).is_absolute() or (len(value) >= 2 and value[1] == ":")


def to_relative_disk_path(value: str) -> str:
    """Return ``value`` relative to ATTACHMENTS_DIR, or unchanged if already
    relative / not under the attachments root."""
    if not value or not _is_absolute(value):
        return value
    root = ATTACHMENTS_DIR.resolve()
    try:
        return Path(value).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        # Outside the attachments root (or unresolvable) -- leave as-is; the
        # download endpoint keeps a legacy-absolute fallback.
        return value


def backfill_relative_disk_paths(conn: sqlite3.Connection) -> int:
    """Rewrite absolute attachment disk_paths in place. Returns count rewritten."""
    rows = conn.execute(
        "SELECT id, disk_path FROM attachments WHERE disk_path IS NOT NULL"
    ).fetchall()
    rewritten = 0
    for row in rows:
        original = row["disk_path"]
        relative = to_relative_disk_path(original)
        if relative != original:
            conn.execute(
                "UPDATE attachments SET disk_path = ? WHERE id = ?",
                (relative, row["id"]),
            )
            rewritten += 1
    return rewritten
