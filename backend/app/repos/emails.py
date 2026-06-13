import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .. import db
from ..config import ATTACHMENTS_DIR
from ..services.audit import audit_snapshot_email, record_audit_event
from ..services.email_serialize import serialize_email
from ..services.text_norm import json_dumps, json_loads, row_to_dict
from ..services import tags as tag_service
from ..services.doc_id import allocate_doc_id
from . import attachments as attachment_repo
from . import duplicates as duplicate_repo


def _fetch_email_rows(
    conn: sqlite3.Connection, email_ids: List[int]
) -> List[sqlite3.Row]:
    if not email_ids:
        return []
    placeholders = ",".join("?" for _ in email_ids)
    return conn.execute(
        f"""
        SELECT e.*,
               GROUP_CONCAT(DISTINCT f.flag) AS flags
        FROM emails e
        LEFT JOIN email_flags f ON f.email_id = e.id
        WHERE e.id IN ({placeholders})
        GROUP BY e.id
        """,
        email_ids,
    ).fetchall()


def _serialize_rows(
    conn: sqlite3.Connection,
    rows: List[sqlite3.Row],
    *,
    conflict_ids: Iterable[int] = (),
    with_counts: bool = True,
) -> List[Dict[str, Any]]:
    """Shared fan-out: one batched lookup each for attachments, tags and pending
    duplicate counts, then serialize. Replaces the per-call-site copy of this
    sequence (snip, ingest_map, list/update/restore, duplicate review)."""
    email_ids = [row["id"] for row in rows]
    conflicts = set(conflict_ids)
    attachments = attachment_repo.attachments_for_emails(conn, email_ids)
    tags = tag_service.tags_for_emails(conn, email_ids)
    counts = duplicate_repo.pending_duplicate_counts(conn, email_ids) if with_counts else {}
    return [
        serialize_email(
            row,
            attachments.get(row["id"], []),
            row["id"] in conflicts,
            counts.get(row["id"], 0),
            tags.get(row["id"], []),
        )
        for row in rows
    ]


def serialize_email_bundle(
    conn: sqlite3.Connection,
    email_ids: Iterable[int],
    *,
    conflict_ids: Iterable[int] = (),
    with_counts: bool = True,
) -> Dict[int, Dict[str, Any]]:
    """Serialize the given emails (fetched with flags) keyed by id."""
    ids = list(email_ids)
    rows = _fetch_email_rows(conn, ids)
    serialized = _serialize_rows(conn, rows, conflict_ids=conflict_ids, with_counts=with_counts)
    return {row["id"]: item for row, item in zip(rows, serialized)}


def serialized_emails_by_id(
    conn: sqlite3.Connection, email_ids: Iterable[int]
) -> Dict[int, Dict[str, Any]]:
    return serialize_email_bundle(conn, email_ids)


def insert_email(
    conn: sqlite3.Connection,
    case_id: int,
    parsed: Any,
    *,
    ingest_job_id: Optional[int] = None,
    derived_from_attachment_id: Optional[int] = None,
    doc_id: Optional[str] = None,
) -> int:
    # A doc_id identifies a *document*, not a card: callers that create a derived
    # row (quoted/attached child, snip part, selection card) pass the source
    # document's doc_id so every card from one uploaded file shares it. Only true
    # document roots (a file's standalone, a manual email) pass None and get a
    # freshly allocated code.
    now = db.utc_now()
    raw = {
        "message_id": parsed.message_id,
        "in_reply_to": parsed.in_reply_to,
        "references": parsed.references,
        "from_addr": parsed.from_addr,
        "to": parsed.to,
        "cc": parsed.cc,
        "date_utc": parsed.date_utc,
        "date_raw": parsed.date_raw,
        "subject": parsed.subject,
        "body_text": getattr(parsed, "body_text_original", None) or parsed.body_text,
        "body_html_raw": parsed.body_html_raw,
        "body_format": parsed.body_format,
        "parse_confidence": parsed.parse_confidence,
        "flags": parsed.flags,
        "boundary_method": getattr(parsed, "boundary_method", "mime"),
        "boundary_evidence": getattr(parsed, "boundary_evidence", []),
        "relation_confidence": getattr(parsed, "relation_confidence", parsed.parse_confidence),
        "source_import_mode": parsed.source_import_mode,
        "source_file_display": parsed.source_file_display,
        "source_size": parsed.source_size,
        "source_mtime": parsed.source_mtime,
        "source_sha256": parsed.source_sha256,
        "notes": getattr(parsed, "notes", ""),
        "important": bool(getattr(parsed, "important", False)),
        "user_edited": bool(getattr(parsed, "user_edited", False)),
        "conversation_index": getattr(parsed, "conversation_index", None),
        "conversation_topic": getattr(parsed, "conversation_topic", None),
    }
    cur = conn.execute(
        """
        INSERT INTO emails
          (case_id, doc_id, source_file, source_file_display, message_id, in_reply_to,
           references_json, from_addr, to_json, cc_json, date_utc, date_raw,
           subject, body_text, body_html_raw, body_html_sanitized, body_format,
           thread_id, parse_confidence, source_kind, parent_email_id,
           chain_source_id, chain_position, manual_chain_order,
           source_import_mode, source_openable, source_size, source_mtime,
           source_sha256, source_blob_sha256, ingest_job_id, derived_from_attachment_id,
           notes, important, user_edited, conversation_index, conversation_topic,
           raw_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            doc_id if doc_id is not None else allocate_doc_id(conn, case_id),
            parsed.source_file,
            parsed.source_file_display,
            parsed.message_id,
            parsed.in_reply_to,
            json_dumps(parsed.references),
            parsed.from_addr,
            json_dumps(parsed.to),
            json_dumps(parsed.cc),
            parsed.date_utc,
            parsed.date_raw,
            parsed.subject,
            parsed.body_text,
            parsed.body_html_raw,
            parsed.body_html_sanitized,
            parsed.body_format,
            parsed.message_id or parsed.subject or parsed.source_file_display,
            parsed.parse_confidence,
            parsed.source_kind,
            parsed.parent_email_id,
            getattr(parsed, "chain_source_id", None),
            getattr(parsed, "chain_position", 0),
            getattr(parsed, "manual_chain_order", None),
            getattr(parsed, "source_import_mode", "upload"),
            int(bool(getattr(parsed, "source_openable", False))),
            getattr(parsed, "source_size", None),
            getattr(parsed, "source_mtime", None),
            getattr(parsed, "source_sha256", None),
            getattr(parsed, "source_blob_sha256", None),
            ingest_job_id,
            derived_from_attachment_id,
            getattr(parsed, "notes", ""),
            int(bool(getattr(parsed, "important", False))),
            int(bool(getattr(parsed, "user_edited", False))),
            getattr(parsed, "conversation_index", None),
            getattr(parsed, "conversation_topic", None),
            json_dumps(raw),
            now,
        ),
    )
    email_id = int(cur.lastrowid)
    for flag in parsed.flags:
        conn.execute(
            """
            INSERT INTO email_flags (email_id, flag, detail_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (email_id, flag, "{}", now),
        )
    conn.execute(
        "INSERT INTO emails_fts (rowid, subject, body_text) VALUES (?, ?, ?)",
        (email_id, parsed.subject, parsed.body_text),
    )
    row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    if row:
        record_audit_event(
            conn,
            case_id=case_id,
            action="email.created",
            entity_type="email",
            entity_id=email_id,
            after=audit_snapshot_email(row),
            metadata={
                "source_import_mode": getattr(parsed, "source_import_mode", "upload"),
                "ingest_job_id": ingest_job_id,
            },
        )
    conn.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (now, case_id))
    return email_id


def update_chain_metadata(
    conn: sqlite3.Connection,
    email_id: int,
    *,
    chain_source_id: Optional[int],
    chain_position: int,
) -> None:
    conn.execute(
        "UPDATE emails SET chain_source_id = ?, chain_position = ? WHERE id = ?",
        (chain_source_id, chain_position, email_id),
    )


def case_email_bodies(conn: sqlite3.Connection, case_id: int) -> List[Tuple[int, str, str]]:
    """Return (id, body_text, source_kind) for every email in a case."""
    rows = conn.execute(
        "SELECT id, body_text, source_kind FROM emails WHERE case_id = ?",
        (case_id,),
    ).fetchall()
    return [(row["id"], row["body_text"] or "", row["source_kind"]) for row in rows]


def delete_email(conn: sqlite3.Connection, email_id: int) -> None:
    """Delete an email and its FTS row. Flags/attachments/edits cascade via FK."""
    attachment_dir = ATTACHMENTS_DIR / str(email_id)
    conn.execute("DELETE FROM emails WHERE id = ?", (email_id,))
    conn.execute("DELETE FROM emails_fts WHERE rowid = ?", (email_id,))
    attachment_repo.remove_attachment_dirs([attachment_dir])


# Han ideographs (incl. CJK Ext-A and compatibility ideographs). Used to decide
# whether a short query should bypass FTS5: the trigram tokenizer only matches
# queries of >= 3 characters, so a 1-2 character Chinese query (e.g. 收, 合同)
# yields nothing from MATCH and must fall back to a LIKE substring scan.
_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def _short_cjk_query(q: str) -> bool:
    """A 1-2 char query containing Han characters needs the LIKE fallback."""
    stripped = q.strip()
    return len(stripped) < 3 and bool(_CJK_RE.search(stripped))


def _like_escape(term: str) -> str:
    """Escape LIKE wildcards so user input is matched literally (ESCAPE '\\')."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def email_filter_parts(
    case_id: int,
    q: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    tag_id: Optional[int] = None,
) -> Tuple[List[str], List[Any], bool]:
    clauses = ["e.case_id = ?", "e.deleted_at IS NULL", "e.superseded_at IS NULL"]
    params: List[Any] = [case_id]
    join_fts = False
    if q:
        stripped = q.strip()
        if _short_cjk_query(stripped):
            # Sub-trigram CJK query: scan the base table directly. No FTS join.
            pattern = f"%{_like_escape(stripped)}%"
            clauses.append(
                "(e.subject LIKE ? ESCAPE '\\' OR e.body_text LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern])
        else:
            join_fts = True
            # Wrap as a quoted phrase so FTS5 query operators in user input
            # (e.g. quotes, *, :, NEAR) are treated literally rather than parsed.
            clauses.append("emails_fts MATCH ?")
            params.append('"' + stripped.replace('"', '""') + '"')
    if date_start:
        clauses.append("e.date_utc >= ?")
        params.append(date_start)
    if date_end:
        clauses.append("e.date_utc <= ?")
        params.append(date_end)
    if tag_id:
        clauses.append("e.id IN (SELECT email_id FROM email_tags WHERE tag_id = ?)")
        params.append(tag_id)
    return clauses, params, join_fts


def count_emails(
    conn: sqlite3.Connection,
    case_id: int,
    q: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    tag_id: Optional[int] = None,
) -> int:
    clauses, params, join_fts = email_filter_parts(case_id, q, date_start, date_end, tag_id)
    join_sql = "JOIN emails_fts ON emails_fts.rowid = e.id" if join_fts else ""
    where_sql = " AND ".join(clauses)
    row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT e.id) AS total
        FROM emails e
        {join_sql}
        WHERE {where_sql}
        """,
        params,
    ).fetchone()
    return int(row["total"] if row else 0)


def list_emails(
    case_id: int,
    view: str = "chrono",
    q: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    tag_id: Optional[int] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    clauses, params, join_fts = email_filter_parts(case_id, q, date_start, date_end, tag_id)
    join_sql = "JOIN emails_fts ON emails_fts.rowid = e.id" if join_fts else ""
    where_sql = " AND ".join(clauses)
    order_sql = (
        """
        e.thread_id ASC,
        CASE WHEN e.parent_email_id IS NULL THEN 0 ELSE 1 END ASC,
        COALESCE(e.date_utc, e.created_at) ASC,
        e.id ASC
        """
        if view == "thread"
        else """
        CASE WHEN e.manual_chrono_order IS NULL THEN 1 ELSE 0 END ASC,
        e.manual_chrono_order ASC,
        COALESCE(e.date_utc, e.created_at) ASC,
        e.id ASC
        """
    )
    with db.get_conn() as conn:
        # Duplicate-candidate scanning is O(n^2), so reads only use the persisted
        # review table. Recompute happens at ingest completion or by explicit API.
        limit_sql = ""
        query_params = list(params)
        if limit is not None:
            safe_limit = max(1, min(int(limit), 500))
            safe_offset = max(0, int(offset))
            limit_sql = "LIMIT ? OFFSET ?"
            query_params.extend([safe_limit, safe_offset])
        rows = conn.execute(
            f"""
            SELECT e.*,
                   GROUP_CONCAT(DISTINCT f.flag) AS flags
            FROM emails e
            {join_sql}
            LEFT JOIN email_flags f ON f.email_id = e.id
            WHERE {where_sql}
            GROUP BY e.id
            ORDER BY {order_sql}
            {limit_sql}
            """,
            query_params,
        ).fetchall()
        conflict_ids = chain_date_conflict_ids(rows)
        return _serialize_rows(conn, rows, conflict_ids=conflict_ids)


def list_emails_page(
    case_id: int,
    view: str = "chrono",
    q: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    tag_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))
    with db.get_conn() as conn:
        total = count_emails(conn, case_id, q, date_start, date_end, tag_id)
    items = list_emails(
        case_id,
        view=view,
        q=q,
        date_start=date_start,
        date_end=date_end,
        tag_id=tag_id,
        limit=safe_limit,
        offset=safe_offset,
    )
    return {
        "items": items,
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "has_more": safe_offset + len(items) < total,
    }


def chain_date_conflict_ids(rows: Iterable[sqlite3.Row]) -> set:
    by_chain: Dict[int, List[sqlite3.Row]] = {}
    for row in rows:
        chain_source_id = row["chain_source_id"]
        if chain_source_id is None:
            continue
        by_chain.setdefault(chain_source_id, []).append(row)

    conflict_ids = set()
    for chain_rows in by_chain.values():
        ordered = sorted(chain_rows, key=lambda row: (row["chain_position"], row["id"]))
        upper_with_latest_date = None
        latest_ts = None
        for row in ordered:
            if not row["date_utc"]:
                continue
            try:
                ts = datetime.fromisoformat(row["date_utc"]).timestamp()
            except ValueError:
                continue
            # In a visible reply chain, lower quoted messages should not be later
            # than messages above them. When they are, preserve that as display
            # evidence instead of rewriting the parsed date.
            if latest_ts is not None and ts > latest_ts:
                conflict_ids.add(row["id"])
                if upper_with_latest_date is not None:
                    conflict_ids.add(upper_with_latest_date["id"])
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts
                upper_with_latest_date = row
    return conflict_ids


def update_email(email_id: int, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {
        "from_addr": "from_addr",
        "to": "to_json",
        "cc": "cc_json",
        "date_utc": "date_utc",
        "date_raw": "date_raw",
        "subject": "subject",
        "body_text": "body_text",
        "notes": "notes",
        "important": "important",
    }
    with db.get_conn() as conn:
        current = conn.execute(
            "SELECT * FROM emails WHERE id = ? AND deleted_at IS NULL",
            (email_id,),
        ).fetchone()
        if not current:
            return None
        now = db.utc_now()
        assignments = []
        params: List[Any] = []
        before_values: Dict[str, Any] = {}
        after_values: Dict[str, Any] = {}
        for api_field, db_field in allowed.items():
            if api_field not in changes:
                continue
            value = changes[api_field]
            if api_field in {"to", "cc"}:
                stored_value = json_dumps(value)
            elif api_field == "important":
                stored_value = int(bool(value))
            else:
                stored_value = value
            old_value = current[db_field]
            if stored_value == old_value:
                continue
            assignments.append(f"{db_field} = ?")
            params.append(stored_value)
            before_values[api_field] = json_loads(old_value, []) if api_field in {"to", "cc"} else old_value
            after_values[api_field] = value
            conn.execute(
                """
                INSERT INTO edits (email_id, field, old_value, new_value, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    email_id,
                    api_field,
                    old_value,
                    stored_value,
                    now,
                ),
            )
        if assignments:
            parsed_fields = {"from_addr", "to", "cc", "date_utc", "date_raw", "subject", "body_text"}
            if any(field in changes for field in parsed_fields):
                assignments.extend(["user_edited = 1"])
            params.append(email_id)
            conn.execute(
                f"UPDATE emails SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
            if "subject" in changes or "body_text" in changes:
                updated = conn.execute(
                    "SELECT subject, body_text FROM emails WHERE id = ?", (email_id,)
                ).fetchone()
                conn.execute(
                    "UPDATE emails_fts SET subject = ?, body_text = ? WHERE rowid = ?",
                    (updated["subject"], updated["body_text"], email_id),
                )
        if "date_utc" in after_values:
            tag_service.sync_undated_tag(conn, current["case_id"], [email_id])
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if assignments:
            record_audit_event(
                conn,
                case_id=row["case_id"],
                action="email.updated",
                entity_type="email",
                entity_id=email_id,
                before=before_values,
                after=after_values,
                metadata={
                    "fields": list(after_values.keys()),
                    "subject": row["subject"],
                },
            )
        chain_rows = [row]
        if row["chain_source_id"] is not None:
            chain_rows = conn.execute(
                "SELECT * FROM emails WHERE case_id = ? AND chain_source_id = ?",
                (row["case_id"], row["chain_source_id"]),
            ).fetchall()
        conflict_ids = chain_date_conflict_ids(chain_rows)
        attachments = attachment_repo.attachments_for_emails(conn, [email_id]).get(email_id, [])
        tags = tag_service.tags_for_emails(conn, [email_id]).get(email_id, [])
        duplicate_counts = duplicate_repo.pending_duplicate_counts(conn, [email_id])
        return serialize_email(
            row,
            attachments,
            email_id in conflict_ids,
            duplicate_counts.get(email_id, 0),
            tags,
        )


def list_deleted_emails(case_id: int) -> List[Dict[str, Any]]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.*,
                   GROUP_CONCAT(DISTINCT f.flag) AS flags
            FROM emails e
            LEFT JOIN email_flags f ON f.email_id = e.id
            WHERE e.case_id = ?
              AND e.deleted_at IS NOT NULL
              AND e.deleted_at >= ?
            GROUP BY e.id
            ORDER BY e.deleted_at DESC, e.id DESC
            """,
            (case_id, db.email_restore_cutoff()),
        ).fetchall()
        email_ids = [row["id"] for row in rows]
        attachments = attachment_repo.attachments_for_emails(conn, email_ids)
        return [serialize_email(row, attachments.get(row["id"], []), False) for row in rows]


def soft_delete_email(email_id: int) -> bool:
    now = db.utc_now()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM emails WHERE id = ? AND deleted_at IS NULL",
            (email_id,),
        ).fetchone()
        if not row:
            return False
        conn.execute("UPDATE emails SET deleted_at = ? WHERE id = ?", (now, email_id))
        conn.execute(
            "UPDATE email_text_mappings SET stale = 1, updated_at = ? "
            "WHERE source_email_id = ? OR target_email_id = ?",
            (now, email_id, email_id),
        )
        after = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        record_audit_event(
            conn,
            case_id=row["case_id"],
            action="email.trashed",
            entity_type="email",
            entity_id=email_id,
            before=audit_snapshot_email(row),
            after=audit_snapshot_email(after),
        )
        conn.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (now, row["case_id"]))
    return True


def restore_email(email_id: int) -> Optional[Dict[str, Any]]:
    now = db.utc_now()
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM emails
            WHERE id = ? AND deleted_at IS NOT NULL AND deleted_at >= ?
            """,
            (email_id, db.email_restore_cutoff()),
        ).fetchone()
        if not row:
            return None
        before = audit_snapshot_email(row)
        conn.execute("UPDATE emails SET deleted_at = NULL WHERE id = ?", (email_id,))
        conn.execute(
            """
            UPDATE email_text_mappings
            SET stale = 0, updated_at = ?
            WHERE (source_email_id = ? OR target_email_id = ?)
              AND source_email_id IN (SELECT id FROM emails WHERE deleted_at IS NULL)
              AND target_email_id IN (SELECT id FROM emails WHERE deleted_at IS NULL)
            """,
            (now, email_id, email_id),
        )
        conn.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (now, row["case_id"]))
        record_audit_event(
            conn,
            case_id=row["case_id"],
            action="email.restored",
            entity_type="email",
            entity_id=email_id,
            before=before,
            after=audit_snapshot_email(conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()),
        )
        return serialize_email_bundle(conn, [email_id]).get(email_id)


def get_email_source(email_id: int) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, source_file, source_file_display, source_import_mode,
                   source_openable, source_sha256, source_blob_sha256
            FROM emails
            WHERE id = ? AND deleted_at IS NULL
            """,
            (email_id,),
        ).fetchone()
        return row_to_dict(row) if row else None
