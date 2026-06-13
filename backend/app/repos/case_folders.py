import sqlite3
from typing import Any, Dict, List, Optional

from .. import db
from ..services.text_norm import row_to_dict


def upsert_case_folder(
    conn: sqlite3.Connection, case_id: int, folder_path: str, recursive: bool
) -> None:
    """Record (or refresh) a tracked folder for a case. ``folder_path`` should be
    the resolved/normalized absolute path so the same folder reached via different
    spellings maps to one row."""
    now = db.utc_now()
    conn.execute(
        """
        INSERT INTO case_folders (case_id, folder_path, recursive, last_scanned_at, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(case_id, folder_path)
        DO UPDATE SET recursive = excluded.recursive, last_scanned_at = excluded.last_scanned_at
        """,
        (case_id, folder_path, int(bool(recursive)), now, now),
    )


def list_case_folders(case_id: int) -> List[Dict[str, Any]]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM case_folders WHERE case_id = ? ORDER BY folder_path COLLATE NOCASE ASC",
            (case_id,),
        ).fetchall()
        return [_serialize(row) for row in rows]


def get_case_folder(
    conn: sqlite3.Connection, case_id: int, folder_id: int
) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM case_folders WHERE case_id = ? AND id = ?",
        (case_id, folder_id),
    ).fetchone()
    return _serialize(row) if row else None


def _serialize(row: sqlite3.Row) -> Dict[str, Any]:
    item = row_to_dict(row)
    item["recursive"] = bool(item.get("recursive"))
    return item
