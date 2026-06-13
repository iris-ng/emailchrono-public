import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .text_norm import json_dumps, json_loads, row_to_dict


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit_snapshot_email(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "subject": row["subject"],
        "from_addr": row["from_addr"],
        "date_utc": row["date_utc"],
        "source_kind": row["source_kind"],
        "source_file_display": row["source_file_display"],
        "deleted_at": row["deleted_at"],
    }


def audit_snapshot_case(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "default_tz": row.get("default_tz"),
        "deleted_at": row.get("deleted_at"),
        "email_count": row.get("email_count"),
        "has_cjk_content": row.get("has_cjk_content"),
    }


def compact_audit_value(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 400 else f"{value[:400]}..."
    if isinstance(value, list):
        return [compact_audit_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {key: compact_audit_value(item) for key, item in value.items()}
    return value


def record_audit_event(
    conn: sqlite3.Connection,
    *,
    case_id: Optional[int],
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    actor: str = "local",
) -> None:
    created_at = utc_now()
    previous = conn.execute(
        "SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    prev_hash = previous["event_hash"] if previous else None
    before_json = json_dumps(compact_audit_value(before)) if before is not None else None
    after_json = json_dumps(compact_audit_value(after)) if after is not None else None
    metadata_json = json_dumps(compact_audit_value(metadata or {}))
    hash_payload = json.dumps(
        {
            "case_id": case_id,
            "actor": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "before_json": before_json,
            "after_json": after_json,
            "metadata_json": metadata_json,
            "created_at": created_at,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    event_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()
    conn.execute(
        """
        INSERT INTO audit_events
          (case_id, actor, action, entity_type, entity_id, before_json, after_json,
           metadata_json, created_at, prev_hash, event_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            actor,
            action,
            entity_type,
            entity_id,
            before_json,
            after_json,
            metadata_json,
            created_at,
            prev_hash,
            event_hash,
        ),
    )


def list_audit_events(
    conn: sqlite3.Connection, case_id: int, limit: int = 200
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM audit_events
        WHERE case_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (case_id, limit),
    ).fetchall()
    events = []
    for row in rows:
        item = row_to_dict(row)
        item["before"] = json_loads(item.pop("before_json", None), None)
        item["after"] = json_loads(item.pop("after_json", None), None)
        item["metadata"] = json_loads(item.pop("metadata_json", None), {})
        events.append(item)
    return events


def record_ingest_completed(
    conn: sqlite3.Connection,
    case_id: int,
    job_id: int,
    *,
    tag_ids: Optional[List[int]] = None,
    quoted_duplicates_removed: int = 0,
    contains_cjk: bool = False,
) -> None:
    """Append a hash-linked audit event summarizing one upload session.

    The durable "which emails came from this upload" record is emails.ingest_job_id;
    this event makes the same information visible in the audit trail. ``email_ids``
    and ``file_names`` may be truncated by compact_audit_value, so ``email_count``
    carries the true total for display.
    """
    job = conn.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        return
    email_rows = conn.execute(
        "SELECT id, source_kind FROM emails WHERE ingest_job_id = ? ORDER BY id",
        (job_id,),
    ).fetchall()
    email_ids = [row["id"] for row in email_rows]
    counts: Dict[str, int] = {}
    for row in email_rows:
        kind = row["source_kind"] or "standalone"
        counts[kind] = counts.get(kind, 0) + 1
    file_rows = conn.execute(
        "SELECT source_file_display FROM ingest_files WHERE job_id = ? ORDER BY id",
        (job_id,),
    ).fetchall()
    tag_names: List[str] = []
    if tag_ids:
        unique_tag_ids = list(dict.fromkeys(tag_ids))
        placeholders = ",".join("?" for _ in unique_tag_ids)
        tag_rows = conn.execute(
            f"""
            SELECT name
            FROM tags
            WHERE case_id = ? AND id IN ({placeholders})
            ORDER BY name COLLATE NOCASE ASC
            """,
            [case_id, *unique_tag_ids],
        ).fetchall()
        tag_names = [row["name"] for row in tag_rows]
    record_audit_event(
        conn,
        case_id=case_id,
        action="ingest.completed",
        entity_type="ingest_job",
        entity_id=job_id,
        metadata={
            "job_id": job_id,
            "status": job["status"],
            "total_files": job["total_files"],
            "processed_files": job["processed_files"],
            "failed_files": job["failed_files"],
            "email_count": len(email_ids),
            "email_ids": email_ids,
            "counts": counts,
            "quoted_duplicates_removed": quoted_duplicates_removed,
            "contains_cjk": contains_cjk,
            "file_names": [row["source_file_display"] for row in file_rows],
            "tag_ids": tag_ids or [],
            "tag_names": tag_names,
        },
    )
