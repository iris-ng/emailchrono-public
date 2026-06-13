import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from fastapi import UploadFile

from .. import db
from ..config import (
    ATTACHMENTS_DIR,
    MAX_ATTACHMENT_BYTES,
    MAX_INGEST_FILE_BYTES,
    STORE_SOURCES,
)
from ..parsers.base import DocumentIngestError, EmailParseResult
from ..parsers.docx import parse_docx_bytes
from ..parsers.eml import parse_eml_bytes
from ..parsers.msg import parse_msg_bytes
from ..parsers.pdf import parse_pdf_bytes
from ..repos import attachments as attachment_repo
from ..repos import case_folders as case_folder_repo
from ..repos import cases as case_repo
from ..repos import dates as date_repo
from ..repos import duplicates as duplicate_repo
from ..repos import emails as email_repo
from ..repos import ingest_jobs as ingest_job_repo
from ..repos import tags as tag_repo
from ..repos import threads as thread_repo
from .audit import record_ingest_completed
from .boilerplate import strip_boilerplate
from .dates import to_utc
from .doc_id import allocate_doc_id
from .ingest_map import (
    record_attachment_mapping,
    record_quoted_mapping,
    record_self_mappings,
)
from .nested_email import parse_nested_email
from .quotes import bodies_similar, extract_quoted_blocks
from . import source_store
from .tags import sync_undated_tag
from .text_norm import canonical_body


SUPPORTED_SUFFIXES = {".eml", ".msg", ".pdf", ".docx"}

# Email attachments are expanded into their own timeline rows recursively (an
# attached email can itself attach emails). Bound the recursion depth and the
# total children per uploaded file so a pathological/malicious file can't blow up
# ingest.
MAX_NEST_DEPTH = 5
MAX_ATTACHED_PER_FILE = 50


@dataclass
class PendingUpload:
    filename: str
    content: bytes
    skip_error: Optional[str] = None


async def ingest_uploads(
    case_id: int, uploads: List[UploadFile], tag_ids: Optional[List[int]] = None
) -> dict:
    pending = [
        PendingUpload(clean_upload_display(upload.filename or "message.eml"), await upload.read(MAX_INGEST_FILE_BYTES + 1))
        for upload in uploads
    ]
    job, default_tz = create_upload_job(case_id, pending)
    run_upload_job(case_id, job["id"], pending, default_tz, tag_ids)
    result = ingest_job_repo.get_ingest_job(case_id, job["id"])
    if result is None:
        raise ValueError("Ingest job not found")
    return result


def create_upload_job(
    case_id: int, uploads: List[PendingUpload], contains_cjk: bool = False
) -> Tuple[dict, str]:
    with db.get_conn() as conn:
        case = case_repo.get_case_by_id(conn, case_id)
        if not case:
            raise ValueError("Case not found")
        if case.get("deleted_at"):
            raise ValueError("Case is in trash; restore it before adding files")
        default_tz = case.get("default_tz") or "UTC"
        job_id = ingest_job_repo.create_ingest_job(conn, case_id, len(uploads), contains_cjk)
    job = ingest_job_repo.get_ingest_job(case_id, job_id)
    if job is None:
        raise ValueError("Ingest job not found")
    return job, default_tz


def run_upload_job(
    case_id: int,
    job_id: int,
    uploads: List[PendingUpload],
    default_tz: str,
    tag_ids: Optional[List[int]] = None,
    contains_cjk: bool = False,
) -> None:
    try:
        for upload in uploads:
            ingest_one_payload(case_id, job_id, upload, default_tz)

        with db.get_conn() as conn:
            quoted_duplicates_removed = reconcile_quoted_duplicates(conn, case_id)
            thread_repo.recompute_case_threads(conn, case_id)

        # Refresh duplicate candidates once per ingest so the chronology read path
        # stays cheap (the scan is O(n^2) over reviewable emails).
        duplicate_repo.recompute_duplicate_candidates(case_id)

        finalize_ingest_job(case_id, job_id, tag_ids, quoted_duplicates_removed, contains_cjk)
    except Exception as exc:
        fail_ingest_job(case_id, job_id, exc)



def ingest_folder(
    case_id: int, folder_path: str, recursive: bool = True, tag_ids: Optional[List[int]] = None
) -> dict:
    job, paths, default_tz = create_folder_job(case_id, folder_path, recursive)
    run_folder_job(case_id, job["id"], paths, default_tz, tag_ids)
    result = ingest_job_repo.get_ingest_job(case_id, job["id"])
    if result is None:
        raise ValueError("Ingest job not found")
    return result


def create_folder_job(
    case_id: int,
    folder_path: str,
    recursive: bool = True,
    skip_existing: bool = False,
    contains_cjk: bool = False,
) -> Tuple[dict, List[Path], str]:
    root = Path(folder_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("Folder not found")

    paths = list_email_paths(root, recursive)
    with db.get_conn() as conn:
        case = case_repo.get_case_by_id(conn, case_id)
        if not case:
            raise ValueError("Case not found")
        if case.get("deleted_at"):
            raise ValueError("Case is in trash; restore it before adding files")
        default_tz = case.get("default_tz") or "UTC"

        skipped: List[Tuple[Path, str]] = []
        if skip_existing:
            paths, skipped = partition_new_files(conn, case_id, paths)

        processable: List[Path] = []
        oversized: List[Path] = []
        for path in paths:
            try:
                size = path.stat().st_size
            except OSError:
                processable.append(path)
                continue
            if size > MAX_INGEST_FILE_BYTES:
                oversized.append(path)
            else:
                processable.append(path)
        paths = processable

        job_id = ingest_job_repo.create_ingest_job(
            conn, case_id, len(paths) + len(oversized), contains_cjk
        )
        for path in oversized:
            ingest_job_repo.add_ingest_file(
                conn,
                job_id,
                str(path),
                "skipped",
                error=f"File exceeds {MAX_INGEST_FILE_BYTES} byte ingest limit.",
                source_import_mode="local_folder",
                source_size=path.stat().st_size,
            )
            ingest_job_repo.update_ingest_job(conn, job_id, processed_delta=1)
        for path, sha in skipped:
            ingest_job_repo.add_ingest_file(
                conn,
                job_id,
                str(path),
                "skipped",
                source_import_mode="local_folder",
                source_sha256=sha,
            )
        # Remember the folder so it can be refreshed later. Store the resolved
        # path so different spellings of the same folder collapse to one row.
        case_folder_repo.upsert_case_folder(conn, case_id, str(root), recursive)
    job = ingest_job_repo.get_ingest_job(case_id, job_id)
    if job is None:
        raise ValueError("Ingest job not found")
    return job, paths, default_tz


def partition_new_files(
    conn, case_id: int, paths: List[Path]
) -> Tuple[List[Path], List[Tuple[Path, str]]]:
    """Split candidate files into (to_process, skipped) by content hash, dropping
    files whose SHA-256 already exists for the case. Unreadable files are left in
    to_process so the normal ingest path surfaces the error."""
    known = {
        row["source_sha256"]
        for row in conn.execute(
            "SELECT DISTINCT source_sha256 FROM emails "
            "WHERE case_id = ? AND deleted_at IS NULL AND source_sha256 IS NOT NULL",
            (case_id,),
        ).fetchall()
    }
    to_process: List[Path] = []
    skipped: List[Tuple[Path, str]] = []
    for path in paths:
        try:
            sha = hash_bytes(path.read_bytes())
        except OSError:
            to_process.append(path)
            continue
        if sha in known:
            skipped.append((path, sha))
        else:
            to_process.append(path)
    return to_process, skipped


def run_folder_job(
    case_id: int,
    job_id: int,
    paths: List[Path],
    default_tz: str,
    tag_ids: Optional[List[int]] = None,
    contains_cjk: bool = False,
) -> None:
    try:
        for path in paths:
            ingest_path(case_id, job_id, path, default_tz)

        with db.get_conn() as conn:
            quoted_duplicates_removed = reconcile_quoted_duplicates(conn, case_id)
            thread_repo.recompute_case_threads(conn, case_id)

        # Refresh duplicate candidates once per ingest so the chronology read path
        # stays cheap (the scan is O(n^2) over reviewable emails).
        duplicate_repo.recompute_duplicate_candidates(case_id)

        finalize_ingest_job(case_id, job_id, tag_ids, quoted_duplicates_removed, contains_cjk)
    except Exception as exc:
        fail_ingest_job(case_id, job_id, exc)


def fail_ingest_job(case_id: int, job_id: int, exc: Exception) -> None:
    with db.get_conn() as conn:
        ingest_job_repo.update_ingest_job(
            conn,
            job_id,
            status="failed",
            error={"message": str(exc), "type": exc.__class__.__name__},
        )
        record_ingest_completed(conn, case_id, job_id)


def finalize_ingest_job(
    case_id: int,
    job_id: int,
    tag_ids: Optional[List[int]],
    quoted_duplicates_removed: int = 0,
    contains_cjk: bool = False,
) -> None:
    """Mark the job completed/failed, apply any upload-time tags to the top-level
    emails it created (standalone + attached, not quoted children), and emit the
    grouped ``ingest.completed`` audit event carrying those tag ids. When the batch
    was flagged as containing Chinese content, sticky-set ``cases.has_cjk_content``
    so the upload checkbox pre-ticks itself on future uploads for this case."""
    if tag_ids:
        with db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id FROM emails
                WHERE ingest_job_id = ? AND source_kind IN ('standalone', 'attached')
                """,
                (job_id,),
            ).fetchall()
        top_level_ids = [row["id"] for row in rows]
        if top_level_ids:
            tag_repo.add_tags_to_emails(case_id, top_level_ids, tag_ids)

    with db.get_conn() as conn:
        job_rows = conn.execute(
            "SELECT id FROM emails WHERE ingest_job_id = ? AND deleted_at IS NULL",
            (job_id,),
        ).fetchall()
        sync_undated_tag(conn, case_id, [row["id"] for row in job_rows])

        status = "completed"
        job = conn.execute(
            "SELECT failed_files, total_files FROM ingest_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if job and job["failed_files"] == job["total_files"] and job["total_files"]:
            status = "failed"
        ingest_job_repo.update_ingest_job(conn, job_id, status=status)
        if contains_cjk:
            case_repo.mark_case_has_cjk(conn, case_id)
        record_ingest_completed(
            conn,
            case_id,
            job_id,
            tag_ids=tag_ids,
            quoted_duplicates_removed=quoted_duplicates_removed,
            contains_cjk=contains_cjk,
        )


async def ingest_one(case_id: int, job_id: int, upload: UploadFile, default_tz: str = "UTC") -> None:
    filename = clean_upload_display(upload.filename or "message.eml")
    if upload.size is not None and upload.size > MAX_INGEST_FILE_BYTES:
        ingest_one_payload(
            case_id,
            job_id,
            PendingUpload(
                filename,
                b"",
                skip_error=f"File exceeds {MAX_INGEST_FILE_BYTES} byte ingest limit.",
            ),
            default_tz,
        )
        return
    content = await upload.read(MAX_INGEST_FILE_BYTES + 1)
    ingest_one_payload(case_id, job_id, PendingUpload(filename, content), default_tz)


def ingest_one_payload(case_id: int, job_id: int, upload: PendingUpload, default_tz: str = "UTC") -> None:
    filename = clean_upload_display(upload.filename or "message.eml")
    if upload.skip_error or len(upload.content) > MAX_INGEST_FILE_BYTES:
        with db.get_conn() as conn:
            ingest_job_repo.add_ingest_file(
                conn,
                job_id,
                filename,
                "skipped",
                error=upload.skip_error or f"File exceeds {MAX_INGEST_FILE_BYTES} byte ingest limit.",
                source_size=len(upload.content) if upload.content else None,
            )
            ingest_job_repo.update_ingest_job(conn, job_id, processed_delta=1)
        return
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        with db.get_conn() as conn:
            ingest_job_repo.add_ingest_file(
                conn,
                job_id,
                filename,
                "failed",
                error="Only .eml, .msg, .pdf, and .docx files are supported.",
            )
            ingest_job_repo.update_ingest_job(conn, job_id, processed_delta=1, failed_delta=1)
        return

    try:
        content = upload.content
        sha256 = hash_bytes(content)
        # Capture the original bytes so uploaded emails become openable and
        # round-trippable (their bytes were otherwise discarded after parsing).
        blob_sha = None
        if STORE_SOURCES:
            source_store.store_source(content, sha256)
            blob_sha = sha256
        parse_and_store(
            case_id,
            job_id,
            content,
            source_file=filename,
            source_file_display=filename,
            source_import_mode="upload",
            source_openable=bool(blob_sha),
            source_size=len(content),
            source_mtime=None,
            source_sha256=sha256,
            source_blob_sha256=blob_sha,
            default_tz=default_tz,
        )
    except DocumentIngestError as exc:
        # Not an email (or no extractable text). Skip without failing the job so a
        # mixed folder of PDFs/.docx never marks the whole ingest failed.
        with db.get_conn() as conn:
            ingest_job_repo.add_ingest_file(
                conn, job_id, filename, "skipped", error=str(exc)
            )
            ingest_job_repo.update_ingest_job(conn, job_id, processed_delta=1)
    except Exception as exc:
        with db.get_conn() as conn:
            ingest_job_repo.add_ingest_file(conn, job_id, filename, "failed", error=str(exc))
            ingest_job_repo.update_ingest_job(conn, job_id, processed_delta=1, failed_delta=1)


def ingest_path(case_id: int, job_id: int, path: Path, default_tz: str = "UTC") -> None:
    display = str(path)
    try:
        stat = path.stat()
        if stat.st_size > MAX_INGEST_FILE_BYTES:
            with db.get_conn() as conn:
                ingest_job_repo.add_ingest_file(
                    conn,
                    job_id,
                    display,
                    "skipped",
                    error=f"File exceeds {MAX_INGEST_FILE_BYTES} byte ingest limit.",
                    source_import_mode="local_folder",
                    source_size=stat.st_size,
                )
                ingest_job_repo.update_ingest_job(conn, job_id, processed_delta=1)
            return
        content = path.read_bytes()
        sha256 = hash_bytes(content)
        # Fold a copy into the managed store too, so the original survives even
        # if the scanned folder later moves (the on-disk path stays the primary).
        blob_sha = None
        if STORE_SOURCES:
            source_store.store_source(content, sha256)
            blob_sha = sha256
        parse_and_store(
            case_id,
            job_id,
            content,
            source_file=str(path),
            source_file_display=display,
            source_import_mode="local_folder",
            source_openable=True,
            source_size=stat.st_size,
            source_mtime=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            source_sha256=sha256,
            source_blob_sha256=blob_sha,
            default_tz=default_tz,
        )
    except DocumentIngestError as exc:
        with db.get_conn() as conn:
            ingest_job_repo.add_ingest_file(
                conn,
                job_id,
                display,
                "skipped",
                error=str(exc),
                source_import_mode="local_folder",
            )
            ingest_job_repo.update_ingest_job(conn, job_id, processed_delta=1)
    except Exception as exc:
        with db.get_conn() as conn:
            ingest_job_repo.add_ingest_file(
                conn,
                job_id,
                display,
                "failed",
                error=str(exc),
                source_import_mode="local_folder",
            )
            ingest_job_repo.update_ingest_job(conn, job_id, processed_delta=1, failed_delta=1)


def parse_and_store(
    case_id: int,
    job_id: int,
    content: bytes,
    *,
    source_file: str,
    source_file_display: str,
    source_import_mode: str,
    source_openable: bool,
    source_size: int,
    source_mtime: Optional[str],
    source_sha256: str,
    default_tz: str,
    source_blob_sha256: Optional[str] = None,
) -> None:
    suffix = Path(source_file_display).suffix.lower()
    if suffix == ".msg":
        parsed = parse_msg_bytes(content, source_file_display, default_tz)
    elif suffix == ".pdf":
        parsed = parse_pdf_bytes(content, source_file_display, default_tz)
    elif suffix == ".docx":
        parsed = parse_docx_bytes(content, source_file_display, default_tz)
    else:
        parsed = parse_eml_bytes(content, source_file_display, default_tz)
    parsed.source_file = source_file
    parsed.source_file_display = source_file_display
    parsed.source_import_mode = source_import_mode
    parsed.source_openable = source_openable
    parsed.source_size = source_size
    parsed.source_mtime = source_mtime
    parsed.source_sha256 = source_sha256
    parsed.source_blob_sha256 = source_blob_sha256
    # Extract quoted/trailing messages from the original body BEFORE cleanup so the
    # reply-chain delimiters and any quoted disclaimers are still intact.
    quoted = extract_quoted_blocks(parsed, parent_email_id=0, default_tz=default_tz)
    clean_body(parsed)
    for quoted_email in quoted:
        clean_body(quoted_email)
    with db.get_conn() as conn:
        # Allocate one doc_id for the whole uploaded file; every row derived from it
        # (standalone, quoted, attached at any depth) carries this same code.
        file_doc_id = allocate_doc_id(conn, case_id)
        email_id = email_repo.insert_email(
            conn, case_id, parsed, ingest_job_id=job_id, doc_id=file_doc_id
        )
        email_repo.update_chain_metadata(conn, email_id, chain_source_id=email_id, chain_position=0)
        warnings = list(parsed.flags)
        attachment_records = persist_attachments(email_id, parsed.attachments, warnings)
        attachment_ids = [attachment_repo.insert_attachment(conn, email_id, *record) for record in attachment_records]
        record_self_mappings(conn, case_id=case_id, email_id=email_id, mapping_kind="parsed")
        # Quoted children that merely re-quote a standalone email are dropped after
        # the whole job by reconcile_quoted_duplicates (standalone wins over quoted).
        # That single pass is order-independent, so we insert every quoted child here
        # and let the end-of-job reconcile remove the duplicates.
        quoted_ids = []
        for chain_position, quoted_email in enumerate(quoted, start=1):
            quoted_email.parent_email_id = email_id
            quoted_email.chain_source_id = email_id
            quoted_email.chain_position = chain_position
            quoted_id = email_repo.insert_email(
                conn, case_id, quoted_email, ingest_job_id=job_id, doc_id=file_doc_id
            )
            quoted_ids.append(quoted_id)
            record_quoted_mapping(
                conn,
                case_id=case_id,
                source_email_id=email_id,
                target_email_id=quoted_id,
                source_start_offset=getattr(quoted_email, "source_start_offset", None),
                source_end_offset=getattr(quoted_email, "source_end_offset", None),
                confidence=0.85 if quoted_email.parse_confidence == "med" else 0.65,
            )
        # Email attachments (forwarded .eml/.msg, message/rfc822 parts, embedded
        # .msg) become first-class 'attached' rows after the quoted children, the
        # raw file staying as a downloadable attachment linked back by id.
        nested_warnings: List[str] = []
        attached_ids = store_attached_emails(
            conn,
            case_id,
            job_id,
            email_id,
            source_file_display,
            list(zip(parsed.attachments, attachment_ids)),
            default_tz,
            depth=1,
            counter=[0],
            start_position=len(quoted) + 1,
            warnings=nested_warnings,
            doc_id=file_doc_id,
        )
        if quoted_ids:
            warnings.append(f"quoted_records:{len(quoted_ids)}")
        if attached_ids:
            warnings.append(f"attached_records:{len(attached_ids)}")
        warnings.extend(nested_warnings)
        ingest_job_repo.add_ingest_file(
            conn,
            job_id,
            source_file_display,
            "parsed",
            email_id,
            warnings=warnings,
            source_import_mode=source_import_mode,
            source_size=source_size,
            source_mtime=source_mtime,
            source_sha256=source_sha256,
            doc_id=file_doc_id,
        )
        ingest_job_repo.update_ingest_job(conn, job_id, processed_delta=1)


def store_attached_emails(
    conn,
    case_id: int,
    job_id: int,
    parent_id: int,
    parent_display: str,
    attachments_with_ids: List[Tuple[Any, int]],
    default_tz: str,
    *,
    depth: int,
    counter: List[int],
    start_position: int,
    warnings: List[str],
    doc_id: str,
) -> List[int]:
    """Expand email-bearing attachments into 'attached' rows under ``parent_id``.

    Recurses into each attached email's own email-attachments, bounded by
    ``MAX_NEST_DEPTH`` and a shared ``MAX_ATTACHED_PER_FILE`` budget (``counter`` is
    a single-element mutable list shared across the recursion for one uploaded
    file). The attached email is threaded by its own headers later in
    ``recompute_case_threads``; ``chain_source_id`` keeps the link to the file it
    came from. ``doc_id`` is the uploaded file's document id, threaded down so every
    attached row at every depth shares it (independent of ``chain_source_id``).
    Returns the ids created at this level and below.
    """
    if depth > MAX_NEST_DEPTH:
        warnings.append(f"attached_depth_limit:{MAX_NEST_DEPTH}")
        return []
    created: List[int] = []
    position = start_position
    for att, attachment_row_id in attachments_with_ids:
        if not getattr(att, "is_email", False):
            continue
        if counter[0] >= MAX_ATTACHED_PER_FILE:
            warnings.append(f"attached_record_limit:{MAX_ATTACHED_PER_FILE}")
            break
        child_display = f"{parent_display} » {att.filename}"
        child = parse_nested_email(att, child_display, default_tz)
        if child is None:
            warnings.append(f"attached_parse_failed:{att.filename or 'attachment'}")
            continue
        clean_body(child)
        child.source_kind = "attached"
        child.parent_email_id = parent_id
        child.chain_source_id = parent_id
        child.chain_position = position
        # The parent/child link is certain (it came out of the file), so record a
        # dedicated boundary + high relation confidence instead of the parser's
        # default "mime" (which would otherwise be persisted into raw_json).
        child.boundary_method = "attached_email"
        child.relation_confidence = "high"
        child.source_openable = False
        child.source_size = att.size
        child.source_sha256 = hash_bytes(att.content) if att.content else None
        position += 1
        child_id = email_repo.insert_email(
            conn,
            case_id,
            child,
            ingest_job_id=job_id,
            derived_from_attachment_id=attachment_row_id,
            doc_id=doc_id,
        )
        record_self_mappings(
            conn,
            case_id=case_id,
            email_id=child_id,
            mapping_kind="parsed",
            note="Attached email text parsed into this card",
        )
        record_attachment_mapping(
            conn,
            case_id=case_id,
            parent_email_id=parent_id,
            attachment_id=attachment_row_id,
            target_email_id=child_id,
        )
        counter[0] += 1
        created.append(child_id)
        # Persist the attached email's own attachments, then recurse into any of
        # those that are themselves emails.
        child_records = persist_attachments(child_id, child.attachments, warnings)
        child_attachment_ids = [attachment_repo.insert_attachment(conn, child_id, *record) for record in child_records]
        created.extend(
            store_attached_emails(
                conn,
                case_id,
                job_id,
                child_id,
                child_display,
                list(zip(child.attachments, child_attachment_ids)),
                default_tz,
                depth=depth + 1,
                counter=counter,
                start_position=1,
                warnings=warnings,
                doc_id=doc_id,
            )
        )
    return created


def recompute_case_dates(case_id: int, default_tz: str) -> int:
    """Re-derive every email's UTC date from its stored raw date under a new matter
    timezone. Dates whose raw value carries an explicit offset are unaffected; naive
    dates shift. Unparseable raw values are left untouched. Returns rows updated.
    """
    updated = 0
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, date_raw, date_utc FROM emails WHERE case_id = ?", (case_id,)
        ).fetchall()
        for row in rows:
            if not row["date_raw"]:
                continue
            iso = to_utc(row["date_raw"], default_tz)
            if iso and iso != row["date_utc"]:
                conn.execute(
                    "UPDATE emails SET date_utc = ? WHERE id = ?", (iso, row["id"])
                )
                updated += 1
        updated += date_repo.repair_case_dates(conn, case_id)
        sync_undated_tag(conn, case_id)
        thread_repo.recompute_case_threads(conn, case_id)
    return updated


def reconcile_quoted_duplicates(conn, case_id: int) -> int:
    """Remove quoted records that duplicate a standalone email in the same case.

    Standalone wins over quoted. This runs after every ingest job so it is
    order-independent: it catches the case where the standalone original arrives
    after a reply that already quoted it.
    """
    bodies = email_repo.case_email_bodies(conn, case_id)
    # Normalize each body once. This is an O(quoted x standalone) comparison, so
    # normalizing inside the inner loop (as the old is_duplicate_of_any did)
    # paid the NFKC+regex cost ~2*quoted*standalone times -- the dominant cost.
    standalone_norms = [
        norm
        for _, body, kind in bodies
        if kind == "standalone" and (norm := canonical_body(body))
    ]
    removed = 0
    for email_id, body, kind in bodies:
        if kind != "quoted":
            continue
        target = canonical_body(body)
        if target and any(bodies_similar(target, sn) for sn in standalone_norms):
            email_repo.delete_email(conn, email_id)
            removed += 1
    return removed


def clean_body(result: EmailParseResult) -> None:
    """Strip disclaimer boilerplate in place, preserving the original for raw_json."""
    cleaned, removed = strip_boilerplate(result.body_text)
    if not removed:
        return
    result.body_text_original = result.body_text
    result.body_text = cleaned
    if "boilerplate_stripped" not in result.flags:
        result.flags.append("boilerplate_stripped")


def persist_attachments(
    email_id: int, attachments: list, warnings: Optional[List[str]] = None
) -> List[Tuple[str, str, int, str, str, bool]]:
    target_dir = ATTACHMENTS_DIR / str(email_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for index, attachment in enumerate(attachments, start=1):
        if attachment.size > MAX_ATTACHMENT_BYTES:
            if warnings is not None:
                warnings.append(
                    f"attachment_size_limit:{attachment.filename or f'attachment-{index}'}"
                )
            continue
        safe_name = safe_filename(attachment.filename or f"attachment-{index}")
        rel_path = f"{email_id}/{index}-{safe_name}"
        path = target_dir / f"{index}-{safe_name}"
        path.write_bytes(attachment.content)
        records.append(
            (
                attachment.filename or safe_name,
                attachment.mime,
                attachment.size,
                rel_path,
                attachment.content_id,
                attachment.is_inline,
            )
        )
    return records


def safe_filename(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {" ", ".", "_", "-"}).strip()
    return cleaned or "attachment"


def list_email_paths(root: Path, recursive: bool) -> List[Path]:
    candidates = root.rglob("*") if recursive else root.iterdir()
    return sorted(
        (path.resolve() for path in candidates if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES),
        key=lambda path: str(path).lower(),
    )


def hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def clean_upload_display(value: str) -> str:
    cleaned = value.replace("\\", "/").strip()
    parts = [part for part in cleaned.split("/") if part and part not in {".", ".."}]
    return "/".join(parts) or Path(value).name or "message.eml"
