import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import db
from ..config import ATTACHMENTS_DIR
from ..services.audit import (
    audit_snapshot_case,
    list_audit_events as audit_list_audit_events,
    record_audit_event,
)
from ..services.text_norm import row_to_dict
from . import attachments as attachment_repo


def list_audit_events(case_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    with db.get_conn() as conn:
        return audit_list_audit_events(conn, case_id, limit)


def create_case(name: str, default_tz: str = "UTC") -> Dict[str, Any]:
    now = db.utc_now()
    public_id = uuid.uuid4().hex
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO cases (name, created_at, updated_at, default_tz, public_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (name.strip() or "Untitled case", now, now, default_tz or "UTC", public_id),
        )
        case = get_case_by_id(conn, cur.lastrowid)
        record_audit_event(
            conn,
            case_id=case["id"],
            action="case.created",
            entity_type="case",
            entity_id=case["id"],
            after=audit_snapshot_case(case),
        )
        return case


def update_case(case_id: int, *, name: Optional[str] = None, default_tz: Optional[str] = None) -> Optional[Dict[str, Any]]:
    assignments: List[str] = []
    params: List[Any] = []
    if name is not None and name.strip():
        assignments.append("name = ?")
        params.append(name.strip())
    if default_tz is not None:
        assignments.append("default_tz = ?")
        params.append(default_tz)
    with db.get_conn() as conn:
        before = get_case_by_id(conn, case_id)
        if not before:
            return None
        if assignments:
            assignments.append("updated_at = ?")
            params.extend([db.utc_now(), case_id])
            conn.execute(f"UPDATE cases SET {', '.join(assignments)} WHERE id = ?", params)
        after = get_case_by_id(conn, case_id)
        if assignments:
            record_audit_event(
                conn,
                case_id=case_id,
                action="case.updated",
                entity_type="case",
                entity_id=case_id,
                before=audit_snapshot_case(before),
                after=audit_snapshot_case(after),
                metadata={"fields": [field.split(" = ")[0] for field in assignments if field != "updated_at = ?"]},
            )
        return after


def mark_case_has_cjk(conn: sqlite3.Connection, case_id: int) -> None:
    """Sticky-flag a case as containing Chinese content (set by a flagged ingest
    batch). Idempotent; only writes (and bumps updated_at) when not already set."""
    conn.execute(
        "UPDATE cases SET has_cjk_content = 1, updated_at = ? "
        "WHERE id = ? AND has_cjk_content = 0",
        (db.utc_now(), case_id),
    )


def list_cases() -> List[Dict[str, Any]]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.*, COUNT(e.id) AS email_count
            FROM cases c
            LEFT JOIN emails e ON e.case_id = c.id AND e.deleted_at IS NULL
            WHERE c.deleted_at IS NULL
            GROUP BY c.id
            ORDER BY c.updated_at DESC, c.id DESC
            """
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def list_deleted_cases() -> List[Dict[str, Any]]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.*, COUNT(e.id) AS email_count
            FROM cases c
            LEFT JOIN emails e ON e.case_id = c.id AND e.deleted_at IS NULL
            WHERE c.deleted_at IS NOT NULL
            GROUP BY c.id
            ORDER BY c.deleted_at DESC, c.id DESC
            """
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def get_case(case_id: int) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        return get_case_by_id(conn, case_id)


def get_case_by_id(conn: sqlite3.Connection, case_id: int) -> Optional[Dict[str, Any]]:
    return _select_case(conn, "c.id = ?", case_id)


def get_case_by_ref(ref: str) -> Optional[Dict[str, Any]]:
    """Resolve a case from a URL identifier.

    Prefers the stable, opaque ``public_id``; falls back to the integer primary
    key so legacy ``/cases/<id>`` bookmarks keep working.
    """
    with db.get_conn() as conn:
        case = _select_case(conn, "c.public_id = ?", ref)
        if case is None and ref.isdigit():
            case = get_case_by_id(conn, int(ref))
        return case


def _select_case(
    conn: sqlite3.Connection, where: str, param: Any
) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        f"""
        SELECT c.*, COUNT(e.id) AS email_count
        FROM cases c
        LEFT JOIN emails e ON e.case_id = c.id AND e.deleted_at IS NULL
        WHERE {where}
        GROUP BY c.id
        """,
        (param,),
    ).fetchone()
    return row_to_dict(row) if row else None


def soft_delete_case(case_id: int) -> bool:
    """Move a case to trash. Emails/attachments are retained for recovery."""
    with db.get_conn() as conn:
        before = get_case_by_id(conn, case_id)
        if not before or before.get("deleted_at") is not None:
            return False
        deleted_at = db.utc_now()
        result = conn.execute(
            "UPDATE cases SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (deleted_at, case_id),
        )
        after = get_case_by_id(conn, case_id)
        record_audit_event(
            conn,
            case_id=case_id,
            action="case.trashed",
            entity_type="case",
            entity_id=case_id,
            before=audit_snapshot_case(before),
            after=audit_snapshot_case(after),
        )
        return result.rowcount > 0


def restore_case(case_id: int) -> bool:
    """Recover a trashed case."""
    with db.get_conn() as conn:
        before = get_case_by_id(conn, case_id)
        if not before or before.get("deleted_at") is None:
            return False
        now = db.utc_now()
        result = conn.execute(
            "UPDATE cases SET deleted_at = NULL, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NOT NULL",
            (now, case_id),
        )
        after = get_case_by_id(conn, case_id)
        record_audit_event(
            conn,
            case_id=case_id,
            action="case.restored",
            entity_type="case",
            entity_id=case_id,
            before=audit_snapshot_case(before),
            after=audit_snapshot_case(after),
        )
        return result.rowcount > 0


def delete_case(case_id: int) -> bool:
    """Permanently remove a case and everything it owns (cascade)."""
    attachment_dirs: List[Path] = []
    with db.get_conn() as conn:
        before = get_case_by_id(conn, case_id)
        if not before:
            return False
        rows = conn.execute("SELECT id FROM emails WHERE case_id = ?", (case_id,)).fetchall()
        attachment_dirs = [ATTACHMENTS_DIR / str(row["id"]) for row in rows]
        record_audit_event(
            conn,
            case_id=case_id,
            action="case.permanently_deleted",
            entity_type="case",
            entity_id=case_id,
            before=audit_snapshot_case(before),
            metadata={"email_ids": [row["id"] for row in rows]},
        )
        result = conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        deleted = result.rowcount > 0
    if deleted:
        attachment_repo.remove_attachment_dirs(attachment_dirs)
    return deleted
