import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .audit import record_audit_event
from .text_norm import row_to_dict


DEFAULT_TAG_COLOR = "#64748b"

# Auto-managed tag applied to emails that have no parsed date. Kept in sync by
# sync_undated_tag() at ingest finalize, on date re-derivation, and on manual
# date edits, so the user can filter dateless messages out of the chronology.
UNDATED_TAG_NAME = "Undated"
UNDATED_TAG_COLOR = "#b45309"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_tags(conn: sqlite3.Connection, case_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM tags WHERE case_id = ? ORDER BY name COLLATE NOCASE ASC",
        (case_id,),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_tag(conn: sqlite3.Connection, tag_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
    return row_to_dict(row) if row else None


def create_tag(
    conn: sqlite3.Connection, case_id: int, name: str, color: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Create a tag or return the existing case tag with the same name."""
    clean_name = (name or "").strip()
    if not clean_name:
        return None
    clean_color = (color or "").strip() or DEFAULT_TAG_COLOR
    case = conn.execute("SELECT id FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        return None
    existing = conn.execute(
        "SELECT * FROM tags WHERE case_id = ? AND name = ? COLLATE NOCASE",
        (case_id, clean_name),
    ).fetchone()
    if existing:
        return row_to_dict(existing)
    try:
        cur = conn.execute(
            "INSERT INTO tags (case_id, name, color, created_at) VALUES (?, ?, ?, ?)",
            (case_id, clean_name, clean_color, utc_now()),
        )
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT * FROM tags WHERE case_id = ? AND name = ?", (case_id, clean_name)
        ).fetchone()
        return row_to_dict(row) if row else None
    tag = get_tag(conn, int(cur.lastrowid))
    record_audit_event(
        conn,
        case_id=case_id,
        action="tag.created",
        entity_type="tag",
        entity_id=tag["id"],
        after=tag,
    )
    return tag


def update_tag(
    conn: sqlite3.Connection,
    tag_id: int,
    *,
    name: Optional[str] = None,
    color: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    before = get_tag(conn, tag_id)
    if not before:
        return None
    assignments: List[str] = []
    params: List[Any] = []
    if name is not None and name.strip():
        assignments.append("name = ?")
        params.append(name.strip())
    if color is not None and color.strip():
        assignments.append("color = ?")
        params.append(color.strip())
    if not assignments:
        return before
    params.append(tag_id)
    try:
        conn.execute(f"UPDATE tags SET {', '.join(assignments)} WHERE id = ?", params)
    except sqlite3.IntegrityError:
        return before
    after = get_tag(conn, tag_id)
    record_audit_event(
        conn,
        case_id=before["case_id"],
        action="tag.updated",
        entity_type="tag",
        entity_id=tag_id,
        before=before,
        after=after,
    )
    return after


def delete_tag(conn: sqlite3.Connection, tag_id: int) -> bool:
    before = get_tag(conn, tag_id)
    if not before:
        return False
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    record_audit_event(
        conn,
        case_id=before["case_id"],
        action="tag.deleted",
        entity_type="tag",
        entity_id=tag_id,
        before=before,
    )
    return True


def tags_for_emails(
    conn: sqlite3.Connection, email_ids: Iterable[int]
) -> Dict[int, List[Dict[str, Any]]]:
    ids = list(email_ids)
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT et.email_id AS _email_id, t.*
        FROM email_tags et
        JOIN tags t ON t.id = et.tag_id
        WHERE et.email_id IN ({placeholders})
        ORDER BY t.name COLLATE NOCASE ASC
        """,
        ids,
    ).fetchall()
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        item = row_to_dict(row)
        email_id = item.pop("_email_id")
        grouped.setdefault(email_id, []).append(item)
    return grouped


def _ids_in_case(
    conn: sqlite3.Connection, table: str, case_id: int, ids: Iterable[int]
) -> List[int]:
    unique = list(dict.fromkeys(int(i) for i in ids))
    if not unique:
        return []
    placeholders = ",".join("?" for _ in unique)
    rows = conn.execute(
        f"SELECT id FROM {table} WHERE case_id = ? AND id IN ({placeholders})",
        [case_id, *unique],
    ).fetchall()
    found = {row["id"] for row in rows}
    return [i for i in unique if i in found]


def add_tags_to_emails(
    conn: sqlite3.Connection, case_id: int, email_ids: List[int], tag_ids: List[int]
) -> int:
    if not email_ids or not tag_ids:
        return 0
    now = utc_now()
    valid_emails = _ids_in_case(conn, "emails", case_id, email_ids)
    valid_tags = _ids_in_case(conn, "tags", case_id, tag_ids)
    if not valid_emails or not valid_tags:
        return 0
    added = 0
    for email_id in valid_emails:
        for tag_id in valid_tags:
            cur = conn.execute(
                "INSERT OR IGNORE INTO email_tags (email_id, tag_id, created_at) VALUES (?, ?, ?)",
                (email_id, tag_id, now),
            )
            added += cur.rowcount
    if added:
        record_audit_event(
            conn,
            case_id=case_id,
            action="email.tagged",
            entity_type="email",
            metadata={"email_ids": valid_emails, "tag_ids": valid_tags, "added": added},
        )
    return added


def sync_undated_tag(
    conn: sqlite3.Connection, case_id: int, email_ids: Optional[Iterable[int]] = None
) -> None:
    """Keep the auto-managed "Undated" tag in step with ``date_utc``.

    Applies the tag to emails with no parsed date and removes it from those that
    have one. Pass ``email_ids`` to limit the sync (a single edited email, or one
    ingest job's rows); ``None`` syncs the whole case. Reuses the audited
    add/remove paths. The tag is created lazily — only when at least one dateless
    email needs it — so cases with fully-dated emails never grow an empty tag."""
    if email_ids is None:
        rows = conn.execute(
            "SELECT id, date_utc FROM emails WHERE case_id = ? AND deleted_at IS NULL",
            (case_id,),
        ).fetchall()
    else:
        ids = list(dict.fromkeys(int(i) for i in email_ids))
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""
            SELECT id, date_utc FROM emails
            WHERE case_id = ? AND deleted_at IS NULL AND id IN ({placeholders})
            """,
            [case_id, *ids],
        ).fetchall()

    undated_ids = [row["id"] for row in rows if not row["date_utc"]]
    dated_ids = [row["id"] for row in rows if row["date_utc"]]

    existing = conn.execute(
        "SELECT id FROM tags WHERE case_id = ? AND name = ? COLLATE NOCASE",
        (case_id, UNDATED_TAG_NAME),
    ).fetchone()
    tag_id: Optional[int] = existing["id"] if existing else None

    if undated_ids:
        if tag_id is None:
            tag = create_tag(conn, case_id, UNDATED_TAG_NAME, UNDATED_TAG_COLOR)
            tag_id = tag["id"] if tag else None
        if tag_id is not None:
            add_tags_to_emails(conn, case_id, undated_ids, [tag_id])
    if dated_ids and tag_id is not None:
        remove_tags_from_emails(conn, case_id, dated_ids, [tag_id])


def remove_tags_from_emails(
    conn: sqlite3.Connection, case_id: int, email_ids: List[int], tag_ids: List[int]
) -> int:
    if not email_ids or not tag_ids:
        return 0
    valid_emails = _ids_in_case(conn, "emails", case_id, email_ids)
    valid_tags = _ids_in_case(conn, "tags", case_id, tag_ids)
    if not valid_emails or not valid_tags:
        return 0
    email_ph = ",".join("?" for _ in valid_emails)
    tag_ph = ",".join("?" for _ in valid_tags)
    cur = conn.execute(
        f"DELETE FROM email_tags WHERE email_id IN ({email_ph}) AND tag_id IN ({tag_ph})",
        [*valid_emails, *valid_tags],
    )
    removed = cur.rowcount
    if removed:
        record_audit_event(
            conn,
            case_id=case_id,
            action="email.untagged",
            entity_type="email",
            metadata={"email_ids": valid_emails, "tag_ids": valid_tags, "removed": removed},
        )
    return removed
