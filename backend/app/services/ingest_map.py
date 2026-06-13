import re
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .. import db
from ..parsers.base import EmailParseResult
from ..parsers.msg import html_to_text
from ..repos import cases as case_repo
from ..repos import emails as email_repo
from ..repos import threads as thread_repo
from ..services.audit import record_audit_event
from ..services.dates import to_utc
from ..services.sanitize import sanitize_html


SOURCE_FIELDS = {"headers", "subject", "body", "html", "attachments"}
TARGET_FIELDS = {"headers", "subject", "body", "html", "attachments", "notes"}
MAPPING_KINDS = {"parsed", "quoted", "attached", "snipped", "manual", "self", "fuzzy"}


def case_ingest_map_summary(case_id: int) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        if not case_repo.get_case_by_id(conn, case_id):
            return None
        source_rows = load_case_rows(conn, case_id)
        target_rows = load_target_rows(conn, case_id)
        stored = load_stored_mappings(conn, case_id, None)
        by_source: Dict[int, List[Dict[str, Any]]] = {}
        inbound = inbound_mapping_counts(conn, case_id)
        for mapping in stored:
            if mapping.get("stale"):
                continue
            by_source.setdefault(int(mapping["source_email_id"]), []).append(mapping)

        sources = []
        covered_chars = 0
        total_chars = 0
        for row in source_rows:
            source_mappings = by_source.get(int(row["id"]), [])
            inbound_count = inbound.get(int(row["id"]), 0)
            lengths = source_field_lengths(conn, row)
            source_total = sum(lengths.values())
            source_covered = 0
            for field, length in lengths.items():
                source_covered += covered_length(
                    length,
                    [
                        mapping
                        for mapping in source_mappings
                        if mapping["source_field"] == field
                    ],
                )
            covered_chars += source_covered
            total_chars += source_total
            sources.append(
                {
                    "email_id": row["id"],
                    "source_file_display": row["source_file_display"],
                    "subject": row["subject"] or "(no subject)",
                    "source_kind": row["source_kind"],
                    "superseded": bool(row["superseded_at"]),
                    "coverage_percent": percent(source_covered, source_total),
                    "covered_chars": source_covered,
                    "total_chars": source_total,
                    "mapping_count": len(source_mappings),
                    "mapping_counts": mapping_kind_counts(source_mappings),
                    "inbound_mapping_count": inbound_count,
                    "mapping_role": mapping_role(len(source_mappings), inbound_count),
                    "mapping_status": mapping_status(len(source_mappings), inbound_count, source_total),
                }
            )

        return {
            "case_id": case_id,
            "summary": {
                "source_count": len(sources),
                "target_count": len(target_rows),
                "coverage_percent": percent(covered_chars, total_chars),
                "covered_chars": covered_chars,
                "total_chars": total_chars,
                "unmapped_chars": max(0, total_chars - covered_chars),
            },
            "sources": sources,
        }


def case_ingest_map_status(case_id: int) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        if not case_repo.get_case_by_id(conn, case_id):
            return None
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS source_count,
              SUM(
                CASE WHEN EXISTS (
                  SELECT 1
                  FROM email_source_field_cache c
                  WHERE c.email_id = e.id
                ) THEN 1 ELSE 0 END
              ) AS cached_source_count,
              SUM(
                CASE WHEN EXISTS (
                  SELECT 1
                  FROM email_text_mappings m
                  WHERE m.case_id = e.case_id
                    AND m.source_email_id = e.id
                    AND m.stale = 0
                ) THEN 1 ELSE 0 END
              ) AS mapped_source_count
            FROM emails e
            WHERE e.case_id = ? AND e.deleted_at IS NULL
            """,
            (case_id,),
        ).fetchone()
        running = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM ingest_jobs
            WHERE case_id = ? AND status = 'running'
            """,
            (case_id,),
        ).fetchone()
        source_count = int(row["source_count"] or 0)
        cached_source_count = int(row["cached_source_count"] or 0)
        running_count = int(running["count"] or 0)
        return {
            "case_id": case_id,
            "ready": source_count > 0 and running_count == 0,
            "source_count": source_count,
            "cached_source_count": cached_source_count,
            "mapped_source_count": int(row["mapped_source_count"] or 0),
            "running_jobs": running_count,
        }


def case_ingest_map(case_id: int) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        if not case_repo.get_case_by_id(conn, case_id):
            return None
        rows = load_case_rows(conn, case_id)
        return build_map(conn, rows, case_id=case_id)


def email_ingest_map(email_id: int) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        source = conn.execute(
            "SELECT case_id FROM emails WHERE id = ? AND deleted_at IS NULL",
            (email_id,),
        ).fetchone()
        if not source:
            return None
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        return build_map(conn, [row], case_id=source["case_id"], source_email_id=email_id)


def create_card_from_source(
    source_email_id: int,
    source_field: str,
    start_offset: int,
    end_offset: int,
    *,
    subject: Optional[str] = None,
    notes: str = "",
    important: bool = False,
) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        source = conn.execute(
            """
            SELECT e.*, c.default_tz
            FROM emails e
            JOIN cases c ON c.id = e.case_id
            WHERE e.id = ? AND e.deleted_at IS NULL
            """,
            (source_email_id,),
        ).fetchone()
        if not source:
            return None
        fields = source_fields(source, conn)
        field = fields.get(source_field)
        if not field or not valid_range(field["text"], start_offset, end_offset):
            return None
        selected_text = field["text"][start_offset:end_offset].strip()
        if len(selected_text) < 3:
            return None

        date_raw = source["date_raw"]
        date_utc = to_utc(date_raw, source["default_tz"] or "UTC") if date_raw else source["date_utc"]
        parsed = EmailParseResult(
            source_file=source["source_file"] or f"selection://email/{source_email_id}",
            source_file_display=f"{source['source_file_display']} selection",
            message_id=None,
            in_reply_to=source["message_id"],
            references=db.json_loads(source["references_json"], []),
            from_addr=source["from_addr"] or "",
            to=db.json_loads(source["to_json"], []),
            cc=db.json_loads(source["cc_json"], []),
            date_utc=date_utc,
            date_raw=date_raw,
            subject=(subject or "").strip() or f"Selection from #{source_email_id}",
            body_text=selected_text,
            body_html_raw="",
            body_html_sanitized=sanitize_html(""),
            body_format="text",
            parse_confidence="high",
            flags=["source_selection"],
            source_kind="snipped",
            parent_email_id=source_email_id,
            chain_source_id=source["chain_source_id"] or source_email_id,
            chain_position=(source["chain_position"] or 0) + 1,
            source_import_mode=source["source_import_mode"],
            source_openable=bool(source["source_openable"]),
            source_size=source["source_size"],
            source_mtime=source["source_mtime"],
            source_sha256=source["source_sha256"],
            boundary_method="manual_selection",
            boundary_evidence=[f"Selected {source_field} text from email #{source_email_id}"],
            relation_confidence="high",
        )
        setattr(parsed, "notes", notes.strip())
        setattr(parsed, "important", bool(important))
        setattr(parsed, "user_edited", True)

        new_id = email_repo.insert_email(
            conn,
            source["case_id"],
            parsed,
            ingest_job_id=source["ingest_job_id"],
            doc_id=source["doc_id"],
        )
        record_mapping(
            conn,
            case_id=source["case_id"],
            source_email_id=source_email_id,
            source_field=source_field,
            start_offset=start_offset,
            end_offset=end_offset,
            target_email_id=new_id,
            target_field="body",
            target_start_offset=0,
            target_end_offset=len(selected_text),
            mapping_kind="manual",
            confidence=1.0,
            transform="selection_to_card",
            created_by="user",
            note="Created card from source selection",
        )
        thread_repo.recompute_case_threads(conn, source["case_id"])
        record_audit_event(
            conn,
            case_id=source["case_id"],
            action="email.created_from_source_text",
            entity_type="email",
            entity_id=new_id,
            metadata={
                "source_email_id": source_email_id,
                "source_field": source_field,
                "start_offset": start_offset,
                "end_offset": end_offset,
            },
        )
        return email_repo.serialize_email_bundle(conn, [new_id], with_counts=False).get(new_id)


def create_card_from_sources(
    case_id: int,
    selections: List[Dict[str, Any]],
    *,
    subject: Optional[str] = None,
    notes: str = "",
    important: bool = False,
) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        case = case_repo.get_case_by_id(conn, case_id)
        if not case or not selections:
            return None

        parts: List[Dict[str, Any]] = []
        first_source: Optional[sqlite3.Row] = None
        for index, selection in enumerate(selections):
            source_email_id = int(selection.get("source_email_id") or 0)
            source_field = str(selection.get("source_field") or "")
            start_offset = int(selection.get("start_offset") or 0)
            end_offset = int(selection.get("end_offset") or 0)
            source = conn.execute(
                "SELECT * FROM emails WHERE id = ? AND case_id = ? AND deleted_at IS NULL",
                (source_email_id, case_id),
            ).fetchone()
            if not source:
                return None
            fields = source_fields(source, conn)
            field = fields.get(source_field)
            if not field or not valid_range(field["text"], start_offset, end_offset):
                return None
            text = field["text"][start_offset:end_offset].strip()
            if len(text) < 3:
                return None
            if first_source is None:
                first_source = source
            parts.append(
                {
                    "source": source,
                    "source_email_id": source_email_id,
                    "source_field": source_field,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "text": text,
                }
            )

        if first_source is None:
            return None

        body = "\n\n".join(part["text"] for part in parts)
        date_raw = first_source["date_raw"]
        date_utc = (
            to_utc(date_raw, case.get("default_tz") or "UTC")
            if date_raw
            else first_source["date_utc"]
        )
        parsed = EmailParseResult(
            source_file=f"grouped-selection://case/{case_id}",
            source_file_display="Grouped source selection",
            message_id=None,
            in_reply_to=first_source["message_id"],
            references=db.json_loads(first_source["references_json"], []),
            from_addr=first_source["from_addr"] or "",
            to=db.json_loads(first_source["to_json"], []),
            cc=db.json_loads(first_source["cc_json"], []),
            date_utc=date_utc,
            date_raw=date_raw,
            subject=(subject or "").strip() or f"Grouped selection from {len(parts)} source ranges",
            body_text=body,
            body_html_raw="",
            body_html_sanitized=sanitize_html(""),
            body_format="text",
            parse_confidence="high",
            flags=["grouped_source_selection"],
            source_kind="snipped",
            parent_email_id=first_source["id"],
            chain_source_id=first_source["chain_source_id"] or first_source["id"],
            chain_position=(first_source["chain_position"] or 0) + 1,
            source_import_mode="manual",
            source_openable=False,
            source_size=None,
            source_mtime=None,
            source_sha256=None,
            boundary_method="multi_selection",
            boundary_evidence=[
                f"Grouped {len(parts)} source ranges into one chronology card"
            ],
            relation_confidence="high",
        )
        setattr(parsed, "notes", notes.strip())
        setattr(parsed, "important", bool(important))
        setattr(parsed, "user_edited", True)

        new_id = email_repo.insert_email(
            conn,
            case_id,
            parsed,
            ingest_job_id=first_source["ingest_job_id"],
            doc_id=first_source["doc_id"],
        )
        cursor = 0
        for index, part in enumerate(parts):
            if index:
                cursor += 2
            target_start = cursor
            target_end = target_start + len(part["text"])
            record_mapping(
                conn,
                case_id=case_id,
                source_email_id=part["source_email_id"],
                source_field=part["source_field"],
                start_offset=part["start_offset"],
                end_offset=part["end_offset"],
                target_email_id=new_id,
                target_field="body",
                target_start_offset=target_start,
                target_end_offset=target_end,
                mapping_kind="manual",
                confidence=1.0,
                transform="multi_selection_to_card",
                created_by="user",
                note="Grouped source selection",
                metadata={"group_index": index + 1, "group_size": len(parts)},
            )
            cursor = target_end

        thread_repo.recompute_case_threads(conn, case_id)
        record_audit_event(
            conn,
            case_id=case_id,
            action="email.created_from_grouped_source_text",
            entity_type="email",
            entity_id=new_id,
            metadata={
                "source_ranges": [
                    {
                        "source_email_id": part["source_email_id"],
                        "source_field": part["source_field"],
                        "start_offset": part["start_offset"],
                        "end_offset": part["end_offset"],
                    }
                    for part in parts
                ],
            },
        )
        return email_repo.serialize_email_bundle(conn, [new_id], with_counts=False).get(new_id)


def record_self_mappings(
    conn: sqlite3.Connection,
    *,
    case_id: int,
    email_id: int,
    mapping_kind: str = "parsed",
    note: str = "Parsed source text captured in this card",
) -> List[int]:
    row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    if not row:
        return []
    mapping_ids: List[int] = []
    for field in source_fields(row, conn).values():
        text = field["text"]
        if not text.strip():
            continue
        mapping_ids.append(
            record_mapping(
                conn,
                case_id=case_id,
                source_email_id=email_id,
                source_field=field["field"],
                start_offset=0,
                end_offset=len(text),
                target_email_id=email_id,
                target_field=field["field"],
                target_start_offset=0,
                target_end_offset=len(text),
                mapping_kind=mapping_kind,
                confidence=1.0,
                transform="identity",
                created_by="system",
                note=note,
            )
        )
    refresh_source_field_cache(conn, row)
    return mapping_ids


def record_quoted_mapping(
    conn: sqlite3.Connection,
    *,
    case_id: int,
    source_email_id: int,
    target_email_id: int,
    source_start_offset: Optional[int],
    source_end_offset: Optional[int],
    confidence: float = 0.85,
    note: str = "Quoted text extracted from parent email body",
) -> Optional[int]:
    if source_start_offset is None or source_end_offset is None:
        return None
    source = conn.execute("SELECT * FROM emails WHERE id = ?", (source_email_id,)).fetchone()
    if not source:
        return None
    body = source["body_text"] or ""
    start = int(source_start_offset)
    end = int(source_end_offset)
    if not valid_range(body, start, end):
        return None
    return record_mapping(
        conn,
        case_id=case_id,
        source_email_id=source_email_id,
        source_field="body",
        start_offset=start,
        end_offset=end,
        target_email_id=target_email_id,
        target_field="body",
        target_start_offset=None,
        target_end_offset=None,
        mapping_kind="quoted",
        confidence=confidence,
        transform="quote_extraction",
        created_by="system",
        note=note,
    )


def record_attachment_mapping(
    conn: sqlite3.Connection,
    *,
    case_id: int,
    parent_email_id: int,
    attachment_id: int,
    target_email_id: int,
) -> Optional[int]:
    parent = conn.execute("SELECT * FROM emails WHERE id = ?", (parent_email_id,)).fetchone()
    attachment = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if not parent or not attachment:
        return None
    field = source_fields(parent, conn).get("attachments")
    if not field:
        return None
    needle = attachment_line(attachment)
    start = field["text"].find(needle)
    if start < 0:
        return None
    end = start + len(needle)
    return record_mapping(
        conn,
        case_id=case_id,
        source_email_id=parent_email_id,
        source_field="attachments",
        start_offset=start,
        end_offset=end,
        target_email_id=target_email_id,
        target_field="body",
        target_start_offset=None,
        target_end_offset=None,
        mapping_kind="attached",
        confidence=1.0,
        transform="attachment_parse",
        created_by="system",
        note="Email parsed from source attachment",
        metadata={
            "attachment_id": attachment_id,
            "filename": attachment["filename"],
            "mime": attachment["mime"],
        },
    )


def record_snipped_mapping(
    conn: sqlite3.Connection,
    *,
    case_id: int,
    source_email_id: int,
    source_field: str,
    start_offset: int,
    end_offset: int,
    target_email_id: int,
    note: str = "",
    snip_id: Optional[int] = None,
    part_index: Optional[int] = None,
) -> int:
    return record_mapping(
        conn,
        case_id=case_id,
        source_email_id=source_email_id,
        source_field=source_field,
        start_offset=start_offset,
        end_offset=end_offset,
        target_email_id=target_email_id,
        target_field="body",
        target_start_offset=None,
        target_end_offset=None,
        mapping_kind="snipped",
        confidence=1.0,
        transform="manual_snip",
        created_by="user",
        note=note,
        snip_id=snip_id,
        part_index=part_index,
    )


def record_exact_mapping(conn: sqlite3.Connection, **kwargs: Any) -> int:
    # Backward-compatible alias for older call sites; new code should name the
    # provenance kind explicitly.
    return record_snipped_mapping(conn, **kwargs)


def record_mapping(
    conn: sqlite3.Connection,
    *,
    case_id: int,
    source_email_id: int,
    source_field: str,
    start_offset: int,
    end_offset: int,
    target_email_id: int,
    target_field: str = "body",
    target_start_offset: Optional[int] = None,
    target_end_offset: Optional[int] = None,
    mapping_kind: str,
    confidence: float = 1.0,
    transform: str = "identity",
    created_by: str = "system",
    stale: bool = False,
    note: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    snip_id: Optional[int] = None,
    part_index: Optional[int] = None,
) -> int:
    if source_field not in SOURCE_FIELDS or target_field not in TARGET_FIELDS or mapping_kind not in MAPPING_KINDS:
        raise ValueError("Invalid text mapping")
    now = db.utc_now()
    cur = conn.execute(
        """
        INSERT INTO email_text_mappings
          (case_id, source_email_id, source_field, start_offset, end_offset,
           target_email_id, target_field, target_start_offset, target_end_offset,
           mapping_kind, confidence, transform, created_by, stale, note, metadata_json,
           snip_id, part_index, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            source_email_id,
            source_field,
            int(start_offset),
            int(end_offset),
            target_email_id,
            target_field,
            target_start_offset,
            target_end_offset,
            mapping_kind,
            max(0.0, min(1.0, float(confidence))),
            transform,
            created_by,
            int(bool(stale)),
            note,
            db.json_dumps(metadata or {}),
            snip_id,
            part_index,
            now,
            now,
        ),
    )
    return int(cur.lastrowid)


def build_map(
    conn: sqlite3.Connection,
    source_rows: Iterable[sqlite3.Row],
    *,
    case_id: int,
    source_email_id: Optional[int] = None,
) -> Dict[str, Any]:
    source_rows = list(source_rows)
    target_rows = load_target_rows(conn, case_id)
    targets_by_id = {row["id"]: row for row in target_rows}
    stored = load_stored_mappings(conn, case_id, source_email_id)
    inbound = inbound_mapping_counts(conn, case_id)
    colors = color_map(stored)

    sources = []
    for row in source_rows:
        refresh_source_field_cache(conn, row)
        fields = []
        source_total = 0
        source_covered = 0
        for field in source_fields(row, conn).values():
            mappings = [
                enrich_mapping(mapping, targets_by_id, colors)
                for mapping in stored
                if mapping["source_email_id"] == row["id"] and mapping["source_field"] == field["field"]
            ]
            coverage = coverage_for_field(field["text"], mappings)
            source_total += coverage["total_chars"]
            source_covered += coverage["covered_chars"]
            fields.append({**field, **coverage, "mappings": mappings})
        sources.append(
            {
                "email_id": row["id"],
                "source_file_display": row["source_file_display"],
                "subject": row["subject"] or "(no subject)",
                "source_kind": row["source_kind"],
                "superseded": bool(row["superseded_at"]),
                "coverage_percent": percent(source_covered, source_total),
                "covered_chars": source_covered,
                "total_chars": source_total,
                "mapping_count": sum(len(field["mappings"]) for field in fields),
                "inbound_mapping_count": inbound.get(int(row["id"]), 0),
                "mapping_role": mapping_role(
                    sum(len(field["mappings"]) for field in fields),
                    inbound.get(int(row["id"]), 0),
                ),
                "mapping_status": mapping_status(
                    sum(len(field["mappings"]) for field in fields),
                    inbound.get(int(row["id"]), 0),
                    source_total,
                ),
                "fields": fields,
            }
        )

    covered_chars = sum(item["covered_chars"] for item in sources)
    total_chars = sum(item["total_chars"] for item in sources)
    return {
        "case_id": case_id,
        "source_email_id": source_email_id,
        "summary": {
            "source_count": len(sources),
            "target_count": len(target_rows),
            "coverage_percent": percent(covered_chars, total_chars),
            "covered_chars": covered_chars,
            "total_chars": total_chars,
            "unmapped_chars": max(0, total_chars - covered_chars),
        },
        "sources": sources,
        "cards": [card_summary(row, colors.get(row["id"], 0)) for row in target_rows],
    }


def load_case_rows(conn: sqlite3.Connection, case_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM emails
        WHERE case_id = ? AND deleted_at IS NULL
        ORDER BY id
        """,
        (case_id,),
    ).fetchall()


def load_target_rows(conn: sqlite3.Connection, case_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM emails
        WHERE case_id = ? AND deleted_at IS NULL AND superseded_at IS NULL
        ORDER BY COALESCE(manual_chrono_order, 999999), COALESCE(date_utc, created_at), id
        """,
        (case_id,),
    ).fetchall()


def load_stored_mappings(
    conn: sqlite3.Connection, case_id: int, source_email_id: Optional[int]
) -> List[Dict[str, Any]]:
    params: List[Any] = [case_id]
    clause = ""
    if source_email_id is not None:
        clause = "AND m.source_email_id = ?"
        params.append(source_email_id)
    rows = conn.execute(
        f"""
        SELECT m.*
        FROM email_text_mappings m
        JOIN emails se ON se.id = m.source_email_id
        JOIN emails te ON te.id = m.target_email_id
        WHERE m.case_id = ? {clause}
          AND se.deleted_at IS NULL
          AND te.deleted_at IS NULL AND te.superseded_at IS NULL
        ORDER BY m.source_email_id, m.source_field, m.start_offset, m.id
        """,
        params,
    ).fetchall()
    mappings = []
    for row in rows:
        item = db.row_to_dict(row)
        item["stale"] = bool(item.get("stale"))
        item["metadata"] = db.json_loads(item.get("metadata_json"), {})
        mappings.append(item)
    return mappings


def inbound_mapping_counts(conn: sqlite3.Connection, case_id: int) -> Dict[int, int]:
    rows = conn.execute(
        """
        SELECT m.target_email_id, COUNT(*) AS count
        FROM email_text_mappings m
        JOIN emails se ON se.id = m.source_email_id
        JOIN emails te ON te.id = m.target_email_id
        WHERE m.case_id = ? AND m.stale = 0
          AND se.deleted_at IS NULL
          AND te.deleted_at IS NULL AND te.superseded_at IS NULL
        GROUP BY m.target_email_id
        """,
        (case_id,),
    ).fetchall()
    return {int(row["target_email_id"]): int(row["count"]) for row in rows}


def source_fields(row: sqlite3.Row, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Dict[str, Any]]:
    to_values = db.json_loads(row["to_json"], [])
    cc_values = db.json_loads(row["cc_json"], [])
    refs = db.json_loads(row["references_json"], [])
    headers = "\n".join(
        line
        for line in [
            f"From: {row['from_addr'] or ''}",
            f"To: {'; '.join(to_values)}",
            f"Cc: {'; '.join(cc_values)}" if cc_values else "",
            f"Date: {row['date_raw'] or row['date_utc'] or ''}",
            f"Message-ID: {row['message_id'] or ''}" if row["message_id"] else "",
            f"In-Reply-To: {row['in_reply_to'] or ''}" if row["in_reply_to"] else "",
            f"References: {' '.join(refs)}" if refs else "",
        ]
        if line.strip()
    )
    html_text = html_to_text(row["body_html_sanitized"] or "").strip()
    body = row["body_text"] or ""
    attachments = attachment_summary(conn, row["id"]) if conn else ""
    fields = [
        ("headers", "Headers", headers),
        ("subject", "Subject", row["subject"] or ""),
        ("body", "Body", body),
        ("html", "HTML text", html_text if html_text and normalize_space(html_text) != normalize_space(body) else ""),
        ("attachments", "Parsed attachments", attachments),
    ]
    return {
        key: {"field": key, "label": label, "text": text, "length": len(text)}
        for key, label, text in fields
        if text.strip()
    }


def refresh_source_field_cache(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    now = db.utc_now()
    seen = set()
    for field in source_fields(row, conn).values():
        seen.add(field["field"])
        blocks = [
            {"start_offset": start, "end_offset": end}
            for start, end, _ in text_blocks(field["text"])
        ]
        conn.execute(
            """
            INSERT INTO email_source_field_cache (email_id, field, length, block_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(email_id, field) DO UPDATE SET
              length = excluded.length,
              block_json = excluded.block_json,
              updated_at = excluded.updated_at
            """,
            (row["id"], field["field"], field["length"], db.json_dumps(blocks), now),
        )
    if seen:
        placeholders = ",".join("?" for _ in seen)
        conn.execute(
            f"DELETE FROM email_source_field_cache WHERE email_id = ? AND field NOT IN ({placeholders})",
            [row["id"], *seen],
        )
    else:
        conn.execute("DELETE FROM email_source_field_cache WHERE email_id = ?", (row["id"],))


def source_field_lengths(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, int]:
    rows = conn.execute(
        "SELECT field, length FROM email_source_field_cache WHERE email_id = ?",
        (row["id"],),
    ).fetchall()
    if not rows:
        refresh_source_field_cache(conn, row)
        rows = conn.execute(
            "SELECT field, length FROM email_source_field_cache WHERE email_id = ?",
            (row["id"],),
        ).fetchall()
    return {cache["field"]: int(cache["length"]) for cache in rows}


def attachment_summary(conn: Optional[sqlite3.Connection], email_id: int) -> str:
    if conn is None:
        return ""
    rows = conn.execute(
        "SELECT * FROM attachments WHERE email_id = ? ORDER BY id",
        (email_id,),
    ).fetchall()
    return "\n".join(attachment_line(row) for row in rows)


def attachment_line(row: sqlite3.Row) -> str:
    return f"#{row['id']} {row['filename']} ({row['mime']}, {row['size']} bytes)"


def text_blocks(text: str) -> List[Tuple[int, int, str]]:
    blocks: List[Tuple[int, int, str]] = []
    for match in re.finditer(r"\S(?:.*?\S)?(?=\n{2,}|\Z)", text, re.DOTALL):
        raw = match.group(0)
        if normalize_space(raw):
            blocks.append((match.start(), match.end(), raw))
    if len(blocks) <= 1:
        blocks = []
        for match in re.finditer(r"[^\n]+", text):
            raw = match.group(0)
            if normalize_space(raw):
                blocks.append((match.start(), match.end(), raw))
    return blocks


def split_ranges(body: str, offsets: List[int]) -> List[Tuple[int, int]]:
    boundaries = [0, *sorted({int(offset) for offset in offsets}), len(body)]
    ranges = []
    for start, end in zip(boundaries, boundaries[1:]):
        while start < end and body[start].isspace():
            start += 1
        while end > start and body[end - 1].isspace():
            end -= 1
        ranges.append((start, end))
    return ranges


def coverage_for_field(text: str, mappings: List[Dict[str, Any]]) -> Dict[str, Any]:
    ranges = merge_ranges(
        [
            (max(0, int(mapping["start_offset"])), min(len(text), int(mapping["end_offset"])))
            for mapping in mappings
            if not mapping.get("stale") and int(mapping["end_offset"]) > int(mapping["start_offset"])
        ]
    )
    covered = sum(end - start for start, end in ranges)
    unmapped = invert_ranges(ranges, len(text))
    return {
        "coverage_percent": percent(covered, len(text)),
        "covered_chars": covered,
        "total_chars": len(text),
        "unmapped_ranges": [{"start_offset": start, "end_offset": end} for start, end in unmapped if text[start:end].strip()],
    }


def covered_length(length: int, mappings: List[Dict[str, Any]]) -> int:
    ranges = merge_ranges(
        [
            (max(0, int(mapping["start_offset"])), min(length, int(mapping["end_offset"])))
            for mapping in mappings
            if int(mapping["end_offset"]) > int(mapping["start_offset"])
        ]
    )
    return sum(end - start for start, end in ranges)


def merge_ranges(ranges: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    ranges = sorted((start, end) for start, end in ranges if end > start)
    if not ranges:
        return []
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def invert_ranges(ranges: List[Tuple[int, int]], length: int) -> List[Tuple[int, int]]:
    result = []
    cursor = 0
    for start, end in ranges:
        if start > cursor:
            result.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < length:
        result.append((cursor, length))
    return result


def enrich_mapping(
    mapping: Dict[str, Any],
    targets_by_id: Dict[int, sqlite3.Row],
    colors: Dict[int, int],
) -> Dict[str, Any]:
    target = targets_by_id.get(mapping["target_email_id"])
    return {
        **mapping,
        "color_index": colors.get(mapping["target_email_id"], 0),
        "target_subject": target["subject"] if target else f"Email #{mapping['target_email_id']}",
        "target_source": target["source_file_display"] if target else "",
    }


def card_summary(row: sqlite3.Row, color_index: int) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "subject": row["subject"] or "(no subject)",
        "from_addr": row["from_addr"] or "",
        "date_utc": row["date_utc"],
        "source_kind": row["source_kind"],
        "source_file_display": row["source_file_display"],
        "color_index": color_index,
    }


def color_map(mappings: List[Dict[str, Any]]) -> Dict[int, int]:
    ids = []
    for mapping in mappings:
        target_id = mapping["target_email_id"]
        if target_id not in ids:
            ids.append(target_id)
    return {target_id: index % 12 for index, target_id in enumerate(ids)}


def mapping_kind_counts(mappings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for mapping in mappings:
        kind = str(mapping["mapping_kind"])
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def mapping_role(outbound_count: int, inbound_count: int) -> str:
    if outbound_count and inbound_count:
        return "source_and_destination"
    if outbound_count:
        return "source"
    if inbound_count:
        return "destination"
    return "untracked"


def mapping_status(outbound_count: int, inbound_count: int, total_chars: int) -> str:
    if total_chars <= 0:
        return "empty"
    if outbound_count:
        return "mapped_source"
    if inbound_count:
        return "created_from_source"
    return "unmapped"


def percent(covered: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return round((covered / total) * 100, 1)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def valid_range(text: str, start: int, end: int) -> bool:
    return 0 <= int(start) < int(end) <= len(text)
