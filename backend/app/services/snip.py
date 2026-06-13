import sqlite3
from typing import Any, Dict, List, Optional

from .. import db
from ..repos import duplicates as duplicate_repo
from ..repos import emails as email_repo
from ..repos import threads as thread_repo
from ..parsers.base import EmailParseResult
from ..services import tags as tag_service
from ..services.audit import audit_snapshot_email, record_audit_event
from ..services.dates import to_utc
from ..services.ingest_map import record_snipped_mapping, split_ranges
from ..services.quotes import (
    ON_WROTE_RE,
    dedupe_text,
    parse_cjk_block,
    parse_on_wrote_detail,
    parse_outlook_block,
    strip_quote_prefixes,
)
from ..services.sanitize import sanitize_html


MIN_PART_CHARS = 3
UNDATED_TAG = "Undated"


class SnipError(ValueError):
    pass


def preview_snip_email(email_id: int, split_offsets: List[int]) -> Optional[List[Dict[str, Any]]]:
    with db.get_conn() as conn:
        source = load_source(conn, email_id)
        if not source:
            return None
        body = normalize_newlines(source["body_text"] or "")
        offsets = validate_offsets(body, split_offsets)
        parts = split_body(body, offsets)
        default_tz = source["default_tz"] or "UTC"
        return [
            draft_from_part(
                build_part(source, segment, index, len(parts), default_tz, offsets),
                segment,
                index,
            )
            for index, segment in enumerate(parts, start=1)
        ]


def snip_email(
    email_id: int, split_offsets: List[int], drafts: Optional[List[Dict[str, Any]]] = None
) -> Optional[List[Dict[str, Any]]]:
    """Split one stored email body into derived email cards."""
    with db.get_conn() as conn:
        source = load_source(conn, email_id)
        if not source:
            return None

        body = normalize_newlines(source["body_text"] or "")
        offsets = validate_offsets(body, split_offsets)
        parts = split_body(body, offsets)
        part_ranges = split_ranges(body, offsets)
        default_tz = source["default_tz"] or "UTC"
        reviewed = validate_reviewed_drafts(parts, drafts)
        now = db.utc_now()

        snip_id = create_snip_record(conn, source, offsets, now)
        created_ids: List[int] = []
        undated_ids: List[int] = []
        for index, segment in enumerate(parts, start=1):
            parsed = (
                build_part_from_draft(source, reviewed[index - 1], index, len(parts), default_tz, offsets)
                if reviewed
                else build_part(source, segment, index, len(parts), default_tz, offsets)
            )
            new_id = email_repo.insert_email(
                conn,
                source["case_id"],
                parsed,
                ingest_job_id=source["ingest_job_id"],
                doc_id=source["doc_id"],
            )
            created_ids.append(new_id)
            if not parsed.date_utc:
                undated_ids.append(new_id)
            conn.execute(
                """
                INSERT INTO email_snip_parts (snip_id, email_id, part_index, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (snip_id, new_id, index, now),
            )
            start, end = part_ranges[index - 1]
            if end > start:
                record_snipped_mapping(
                    conn,
                    case_id=source["case_id"],
                    source_email_id=source["id"],
                    source_field="body",
                    start_offset=start,
                    end_offset=end,
                    target_email_id=new_id,
                    note="Created by manual Snip",
                    snip_id=snip_id,
                    part_index=index,
                )
            copy_tags(conn, source["id"], new_id, now)
            if index == 1:
                copy_attachments(conn, source["id"], new_id, now)

        # Any snip card that ended up without a parseable date is tagged "Undated"
        # so it stays in the chronology (sorted by created_at) and is easy to find
        # and fix later, instead of failing the whole snip.
        if undated_ids:
            undated_tag = tag_service.create_tag(conn, source["case_id"], UNDATED_TAG)
            if undated_tag:
                tag_service.add_tags_to_emails(
                    conn, source["case_id"], undated_ids, [undated_tag["id"]]
                )

        conn.execute(
            """
            UPDATE emails
            SET superseded_by_snip_id = ?, superseded_at = ?
            WHERE id = ?
            """,
            (snip_id, now, source["id"]),
        )
        updated_source = conn.execute("SELECT * FROM emails WHERE id = ?", (source["id"],)).fetchone()
        record_audit_event(
            conn,
            case_id=source["case_id"],
            action="email.snipped",
            entity_type="email",
            entity_id=source["id"],
            before=audit_snapshot_email(source),
            after=audit_snapshot_email(updated_source),
            metadata={
                "snip_id": snip_id,
                "split_offsets": offsets,
                "created_email_ids": created_ids,
            },
        )
        thread_repo.recompute_case_threads(conn, source["case_id"])

        rows = fetch_rows(conn, created_ids)
        conflict_ids = email_repo.chain_date_conflict_ids(rows)
        bundle = email_repo.serialize_email_bundle(conn, created_ids, conflict_ids=conflict_ids)
        serialized = [bundle[row["id"]] for row in rows]

    duplicate_repo.recompute_duplicate_candidates(int(source["case_id"]))
    return serialized


def load_source(conn: sqlite3.Connection, email_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT e.*, c.default_tz
        FROM emails e
        JOIN cases c ON c.id = e.case_id
        WHERE e.id = ? AND e.deleted_at IS NULL AND e.superseded_at IS NULL
        """,
        (email_id,),
    ).fetchone()


def normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def validate_offsets(body: str, split_offsets: List[int]) -> List[int]:
    if not body.strip():
        raise SnipError("Email body is empty; there is nothing to snip")
    offsets = sorted({int(offset) for offset in split_offsets})
    if not offsets:
        raise SnipError("Add at least one split line before applying Snip")
    if offsets[0] <= 0 or offsets[-1] >= len(body):
        raise SnipError("Split lines must be inside the email body")
    parts = split_body(body, offsets)
    if any(len(part.strip()) < MIN_PART_CHARS for part in parts):
        raise SnipError("Split lines cannot create empty email cards")
    return offsets


def split_body(body: str, offsets: List[int]) -> List[str]:
    boundaries = [0, *offsets, len(body)]
    return [body[start:end].strip() for start, end in zip(boundaries, boundaries[1:])]


def create_snip_record(conn: sqlite3.Connection, source: sqlite3.Row, offsets: List[int], now: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO email_snips (case_id, source_email_id, split_offsets_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (source["case_id"], source["id"], db.json_dumps(offsets), now),
    )
    return int(cur.lastrowid)


def build_part(
    source: sqlite3.Row,
    segment: str,
    index: int,
    total: int,
    default_tz: str,
    offsets: List[int],
) -> EmailParseResult:
    inferred = infer_metadata(segment, default_tz) if index > 1 else None
    metadata = inferred or inherited_metadata(source, segment, index)
    flags = ["manual_snip", f"snip_part:{index}_of_{total}"]
    if index > 1 and inferred is None:
        flags.append("manual_snip_needs_review")

    references = db.json_loads(source["references_json"], [])
    original_message_id = source["message_id"]
    parsed = EmailParseResult(
        source_file=source["source_file"] or f"snip://email/{source['id']}",
        source_file_display=f"{source['source_file_display']} snip #{index}",
        message_id=original_message_id if index == 1 else None,
        in_reply_to=metadata.get("in_reply_to") or (original_message_id if index > 1 else source["in_reply_to"]),
        references=metadata.get("references") or (
            references
            if index == 1
            else dedupe_text([*references, *[ref for ref in [original_message_id] if ref]])
        ),
        from_addr=metadata["from_addr"],
        to=metadata["to"],
        cc=metadata["cc"],
        date_utc=metadata["date_utc"],
        date_raw=metadata["date_raw"],
        subject=metadata["subject"],
        body_text=metadata["body_text"],
        body_html_raw="",
        body_html_sanitized=sanitize_html(""),
        body_format="text",
        parse_confidence=metadata["parse_confidence"],
        flags=flags,
        source_kind="snipped",
        parent_email_id=source["id"],
        chain_source_id=source["chain_source_id"] or source["id"],
        chain_position=(source["chain_position"] or 0) + index,
        source_import_mode=source["source_import_mode"],
        source_openable=bool(source["source_openable"]),
        source_size=source["source_size"],
        source_mtime=source["source_mtime"],
        source_sha256=source["source_sha256"],
        attachments=[],
        boundary_method="manual_snip",
        boundary_evidence=[
            f"Manual Snip from email #{source['id']}",
            f"Split offsets: {', '.join(str(offset) for offset in offsets)}",
        ],
        relation_confidence="high",
    )
    setattr(parsed, "notes", "" if index > 1 else source["notes"] or "")
    setattr(parsed, "important", bool(source["important"]) if index == 1 else False)
    setattr(parsed, "user_edited", True)
    return parsed


def draft_from_part(parsed: EmailParseResult, source_segment: str, index: int) -> Dict[str, Any]:
    return {
        "part_index": index,
        "source_segment": source_segment,
        "from_addr": parsed.from_addr,
        "to": parsed.to,
        "cc": parsed.cc,
        "date_raw": parsed.date_raw,
        "subject": parsed.subject,
        "body_text": parsed.body_text,
        "notes": getattr(parsed, "notes", ""),
        "important": bool(getattr(parsed, "important", False)),
        "parse_confidence": parsed.parse_confidence,
        "flags": parsed.flags,
        "approved": False,
    }


def validate_reviewed_drafts(
    parts: List[str], drafts: Optional[List[Dict[str, Any]]]
) -> Optional[List[Dict[str, Any]]]:
    if drafts is None or not drafts:
        return None
    if len(drafts) != len(parts):
        raise SnipError("Reviewed Snip cards do not match the split segments")
    ordered = sorted(drafts, key=lambda item: int(item.get("part_index") or 0))
    for expected_index, draft in enumerate(ordered, start=1):
        if int(draft.get("part_index") or 0) != expected_index:
            raise SnipError("Reviewed Snip cards are out of sequence")
        if not draft.get("approved"):
            raise SnipError("Approve every proposed Snip card before ingesting")
        if len(str(draft.get("body_text") or "").strip()) < MIN_PART_CHARS:
            raise SnipError("Approved Snip cards cannot have empty body text")
    return ordered


def build_part_from_draft(
    source: sqlite3.Row,
    draft: Dict[str, Any],
    index: int,
    total: int,
    default_tz: str,
    offsets: List[int],
) -> EmailParseResult:
    date_raw = str(draft.get("date_raw") or "").strip() or None
    # Fail gracefully: an unparseable (or absent) date must not block the snip.
    # The card is created without a resolved date_utc; the snip_email caller
    # tags every such card "Undated" so it stays visible and flagged for review.
    date_utc = to_utc(date_raw, default_tz) if date_raw else None

    references = db.json_loads(source["references_json"], [])
    original_message_id = source["message_id"]
    flags = ["manual_snip", f"snip_part:{index}_of_{total}", "manual_snip_reviewed"]
    parsed = EmailParseResult(
        source_file=source["source_file"] or f"snip://email/{source['id']}",
        source_file_display=f"{source['source_file_display']} snip #{index}",
        message_id=original_message_id if index == 1 else None,
        in_reply_to=original_message_id if index > 1 else source["in_reply_to"],
        references=references if index == 1 else dedupe_text([*references, *[ref for ref in [original_message_id] if ref]]),
        from_addr=str(draft.get("from_addr") or "").strip(),
        to=clean_list(draft.get("to")),
        cc=clean_list(draft.get("cc")),
        date_utc=date_utc,
        date_raw=date_raw,
        subject=str(draft.get("subject") or "").strip() or "(no subject)",
        body_text=str(draft.get("body_text") or "").strip(),
        body_html_raw="",
        body_html_sanitized=sanitize_html(""),
        body_format="text",
        parse_confidence="high",
        flags=flags,
        source_kind="snipped",
        parent_email_id=source["id"],
        chain_source_id=source["chain_source_id"] or source["id"],
        chain_position=(source["chain_position"] or 0) + index,
        source_import_mode=source["source_import_mode"],
        source_openable=bool(source["source_openable"]),
        source_size=source["source_size"],
        source_mtime=source["source_mtime"],
        source_sha256=source["source_sha256"],
        attachments=[],
        boundary_method="manual_snip",
        boundary_evidence=[
            f"Manual Snip from email #{source['id']}",
            f"Split offsets: {', '.join(str(offset) for offset in offsets)}",
            "Reviewed before ingest",
        ],
        relation_confidence="high",
    )
    setattr(parsed, "notes", str(draft.get("notes") or "").strip())
    setattr(parsed, "important", bool(draft.get("important")))
    setattr(parsed, "user_edited", True)
    return parsed


def clean_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def inherited_metadata(source: sqlite3.Row, segment: str, index: int) -> Dict[str, Any]:
    return {
        "from_addr": source["from_addr"] if index == 1 else "",
        "to": db.json_loads(source["to_json"], []),
        "cc": db.json_loads(source["cc_json"], []),
        "date_utc": source["date_utc"] if index == 1 else None,
        "date_raw": source["date_raw"] if index == 1 else None,
        "subject": source["subject"] or "(no subject)",
        "body_text": segment,
        "parse_confidence": source["parse_confidence"] if index == 1 else "low",
        "in_reply_to": None,
        "references": None,
    }


def infer_metadata(segment: str, default_tz: str) -> Optional[Dict[str, Any]]:
    for parser in (parse_outlook_block, parse_cjk_block):
        block = parser(segment, default_tz)
        if block:
            return {
                "from_addr": block.from_addr,
                "to": block.to,
                "cc": block.cc,
                "date_utc": block.date_utc,
                "date_raw": block.date_raw,
                "subject": block.subject or "(no subject)",
                "body_text": block.body_text,
                "parse_confidence": block.confidence,
                "in_reply_to": None,
                "references": None,
            }

    match = ON_WROTE_RE.match(segment)
    if not match:
        return None
    date_raw, from_addr = parse_on_wrote_detail(match.group("detail"))
    date_utc = to_utc(date_raw, default_tz) if date_raw else None
    body = strip_quote_prefixes(segment[match.end() :].strip())
    if not body:
        return None
    return {
        "from_addr": from_addr,
        "to": [],
        "cc": [],
        "date_utc": date_utc,
        "date_raw": date_raw,
        "subject": "(no subject)",
        "body_text": body,
        "parse_confidence": "med" if date_utc else "low",
        "in_reply_to": None,
        "references": None,
    }


def copy_tags(conn: sqlite3.Connection, source_email_id: int, new_email_id: int, now: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO email_tags (email_id, tag_id, created_at)
        SELECT ?, tag_id, ?
        FROM email_tags
        WHERE email_id = ?
        """,
        (new_email_id, now, source_email_id),
    )


def copy_attachments(conn: sqlite3.Connection, source_email_id: int, new_email_id: int, now: str) -> None:
    conn.execute(
        """
        INSERT INTO attachments
          (email_id, filename, mime, size, disk_path, content_id, is_inline, created_at)
        SELECT ?, filename, mime, size, disk_path, content_id, is_inline, ?
        FROM attachments
        WHERE email_id = ?
        """,
        (new_email_id, now, source_email_id),
    )


def fetch_rows(conn: sqlite3.Connection, email_ids: List[int]) -> List[sqlite3.Row]:
    if not email_ids:
        return []
    placeholders = ",".join("?" for _ in email_ids)
    order = " ".join(
        ["CASE", *[f"WHEN e.id = ? THEN {index}" for index, _ in enumerate(email_ids)], "END"]
    )
    return conn.execute(
        f"""
        SELECT e.*, GROUP_CONCAT(DISTINCT f.flag) AS flags
        FROM emails e
        LEFT JOIN email_flags f ON f.email_id = e.id
        WHERE e.id IN ({placeholders})
        GROUP BY e.id
        ORDER BY {order}
        """,
        [*email_ids, *email_ids],
    ).fetchall()
