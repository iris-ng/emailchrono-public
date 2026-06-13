import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .. import db
from ..config import ATTACHMENTS_DIR
from ..services.text_norm import row_to_dict


def insert_attachment(
    conn: sqlite3.Connection,
    email_id: int,
    filename: str,
    mime: str,
    size: int,
    disk_path: str,
    content_id: Optional[str],
    is_inline: bool,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO attachments
          (email_id, filename, mime, size, disk_path, content_id, is_inline, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (email_id, filename, mime, size, disk_path, content_id, int(is_inline), db.utc_now()),
    )
    return int(cur.lastrowid)


def remove_attachment_dirs(paths: Iterable[Path]) -> None:
    root = ATTACHMENTS_DIR.resolve()
    for path in paths:
        resolved = path.resolve()
        if resolved == root or root not in resolved.parents:
            continue
        if resolved.exists():
            shutil.rmtree(resolved, ignore_errors=True)


def attachments_for_emails(
    conn: sqlite3.Connection, email_ids: Iterable[int]
) -> Dict[int, List[Dict[str, Any]]]:
    ids = list(email_ids)
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM attachments WHERE email_id IN ({placeholders}) ORDER BY id", ids
    ).fetchall()
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        item = row_to_dict(row)
        item["is_inline"] = bool(item["is_inline"])
        item.pop("disk_path", None)
        grouped.setdefault(row["email_id"], []).append(item)
    return grouped


def get_attachment(attachment_id: int) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
        ).fetchone()
        return row_to_dict(row) if row else None
