import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..repos import cases as case_repo
from ..repos import duplicates as duplicate_repo
from ..repos import emails as email_repo
from ..repos import ordering as ordering_repo
from ..repos import threads as thread_repo
from ..models.schemas import (
    ChainOrderUpdate,
    ChronologyOrderUpdate,
    DuplicateCandidateUpdate,
    DuplicateClusterResolve,
    EmailCreate,
    EmailSnipRequest,
    EmailUpdate,
    SourceCardCreate,
    SourceCardGroupCreate,
)
from ..parsers.base import EmailParseResult
from ..services.dates import to_utc
from ..services.ingest import SUPPORTED_SUFFIXES
from ..services.ingest_map import (
    case_ingest_map,
    case_ingest_map_status,
    case_ingest_map_summary,
    create_card_from_source,
    create_card_from_sources,
    email_ingest_map,
    record_self_mappings,
)
from ..services.sanitize import sanitize_html
from ..services.snip import SnipError, preview_snip_email, snip_email
from ..services import source_store

router = APIRouter(tags=["emails"])


@router.get("/api/cases/{case_id}/emails")
def list_case_emails(
    case_id: int,
    view: str = Query(default="chrono"),
    q: str = Query(default=""),
    date_start: str = Query(default="", alias="dateStart"),
    date_end: str = Query(default="", alias="dateEnd"),
    tag_id: Optional[int] = Query(default=None, alias="tag"),
):
    if view not in {"chrono", "thread"}:
        raise HTTPException(status_code=400, detail="view must be chrono or thread")
    return email_repo.list_emails(
        case_id,
        view=view,
        q=q or None,
        date_start=date_start or None,
        date_end=date_end or None,
        tag_id=tag_id,
    )


@router.get("/api/cases/{case_id}/emails/page")
def list_case_emails_page(
    case_id: int,
    view: str = Query(default="chrono"),
    q: str = Query(default=""),
    date_start: str = Query(default="", alias="dateStart"),
    date_end: str = Query(default="", alias="dateEnd"),
    tag_id: Optional[int] = Query(default=None, alias="tag"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if view not in {"chrono", "thread"}:
        raise HTTPException(status_code=400, detail="view must be chrono or thread")
    return email_repo.list_emails_page(
        case_id,
        view=view,
        q=q or None,
        date_start=date_start or None,
        date_end=date_end or None,
        tag_id=tag_id,
        limit=limit,
        offset=offset,
    )


@router.get("/api/cases/{case_id}/emails/trash")
def list_case_email_trash(case_id: int):
    return email_repo.list_deleted_emails(case_id)


@router.get("/api/cases/{case_id}/ingest-map")
def get_case_ingest_map(case_id: int):
    result = case_ingest_map(case_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return result


@router.get("/api/cases/{case_id}/ingest-map-summary")
def get_case_ingest_map_summary(case_id: int):
    result = case_ingest_map_summary(case_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return result


@router.get("/api/cases/{case_id}/ingest-map-status")
def get_case_ingest_map_status(case_id: int):
    result = case_ingest_map_status(case_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return result


@router.get("/api/emails/{email_id}/ingest-map")
def get_email_ingest_map(email_id: int):
    result = email_ingest_map(email_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return result


@router.post("/api/emails/{email_id}/create-card-from-source")
def create_email_from_source_text(email_id: int, payload: SourceCardCreate):
    result = create_card_from_source(
        email_id,
        payload.source_field,
        payload.start_offset,
        payload.end_offset,
        subject=payload.subject,
        notes=payload.notes,
        important=payload.important,
    )
    if result is None:
        raise HTTPException(status_code=400, detail="Card could not be created from source text")
    duplicate_repo.recompute_duplicate_candidates(result["case_id"])
    return result


@router.post("/api/cases/{case_id}/create-card-from-sources")
def create_email_from_grouped_source_text(case_id: int, payload: SourceCardGroupCreate):
    result = create_card_from_sources(
        case_id,
        [selection.dict() for selection in payload.selections],
        subject=payload.subject,
        notes=payload.notes,
        important=payload.important,
    )
    if result is None:
        raise HTTPException(status_code=400, detail="Card could not be created from source selections")
    duplicate_repo.recompute_duplicate_candidates(case_id)
    return result


@router.get("/api/cases/{case_id}/duplicate-candidates")
def list_case_duplicate_candidates(
    case_id: int,
    email_id: Optional[int] = Query(default=None, alias="emailId"),
    status: str = Query(default="pending"),
):
    if status not in {"pending", "duplicate", "dissimilar"}:
        raise HTTPException(status_code=400, detail="status must be pending, duplicate, or dissimilar")
    if not case_repo.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    return duplicate_repo.list_duplicate_candidates(case_id, email_id=email_id, status=status)


@router.post("/api/cases/{case_id}/duplicate-candidates/recompute")
def recompute_case_duplicate_candidates(case_id: int):
    if not case_repo.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    count = duplicate_repo.recompute_duplicate_candidates(case_id)
    return {"ok": True, "changed": count}


@router.get("/api/cases/{case_id}/duplicate-clusters")
def list_case_duplicate_clusters(case_id: int):
    if not case_repo.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    return duplicate_repo.list_duplicate_clusters(case_id)


@router.post("/api/cases/{case_id}/duplicate-clusters/resolve")
def resolve_case_duplicate_cluster(case_id: int, payload: DuplicateClusterResolve):
    if not case_repo.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    resolved = duplicate_repo.resolve_duplicate_cluster(
        case_id, payload.canonical_email_id, payload.duplicate_email_ids
    )
    return {"ok": True, "resolved": resolved}


@router.post("/api/cases/{case_id}/duplicate-candidates/resolve-exact")
def resolve_case_exact_duplicates(case_id: int):
    if not case_repo.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    resolved = duplicate_repo.resolve_exact_duplicates(case_id)
    return {"ok": True, "resolved": resolved}


@router.patch("/api/duplicate-candidates/{candidate_id}")
def patch_duplicate_candidate(candidate_id: int, payload: DuplicateCandidateUpdate):
    candidate = duplicate_repo.update_duplicate_candidate(
        candidate_id,
        status=payload.status,
        canonical_email_id=payload.canonical_email_id,
        duplicate_email_id=payload.duplicate_email_id,
    )
    if not candidate:
        raise HTTPException(status_code=400, detail="Duplicate candidate could not be updated")
    return candidate


@router.post("/api/cases/{case_id}/emails")
def create_case_email(case_id: int, payload: EmailCreate):
    with db.get_conn() as conn:
        case = case_repo.get_case_by_id(conn, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        date_raw = (payload.date_raw or "").strip()
        date_utc = to_utc(date_raw, case.get("default_tz") or "UTC") if date_raw else None
        if date_raw and not date_utc:
            raise HTTPException(status_code=400, detail="Date could not be parsed")

        body_text = payload.body_text.strip()
        parsed = EmailParseResult(
            source_file=f"manual://case/{case_id}",
            source_file_display="Manual entry",
            message_id=None,
            in_reply_to=None,
            references=[],
            from_addr=payload.from_addr.strip(),
            to=clean_address_list(payload.to),
            cc=clean_address_list(payload.cc),
            date_utc=date_utc,
            date_raw=date_raw or None,
            subject=payload.subject.strip() or "(no subject)",
            body_text=body_text,
            body_html_raw="",
            body_html_sanitized=sanitize_html(""),
            body_format="text",
            parse_confidence="high",
            flags=[],
            source_kind="standalone",
            source_import_mode="manual",
            source_openable=False,
        )
        setattr(parsed, "notes", payload.notes.strip())
        setattr(parsed, "important", bool(payload.important))
        setattr(parsed, "user_edited", True)

        email_id = email_repo.insert_email(conn, case_id, parsed)
        record_self_mappings(
            conn,
            case_id=case_id,
            email_id=email_id,
            mapping_kind="manual",
            note="Manual card text captured in this card",
        )
        thread_repo.recompute_case_threads(conn, case_id)
    duplicate_repo.recompute_duplicate_candidates(case_id)
    with db.get_conn() as conn:
        email = email_repo.serialize_email_bundle(conn, [email_id]).get(email_id)
        if not email:
            raise HTTPException(status_code=500, detail="Email could not be created")
        return email


@router.patch("/api/emails/{email_id}")
def patch_email(email_id: int, payload: EmailUpdate):
    changes = payload.dict(exclude_unset=True)
    if "date_utc" in changes:
        normalize_email_update_date(email_id, changes)
    email = email_repo.update_email(email_id, changes)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return email


@router.post("/api/emails/{email_id}/snip")
def snip_email_card(email_id: int, payload: EmailSnipRequest):
    try:
        emails = snip_email(
            email_id,
            payload.split_offsets,
            [part.dict() for part in payload.parts] if payload.parts else None,
        )
    except SnipError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if emails is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return emails


@router.post("/api/emails/{email_id}/snip/preview")
def preview_snip_email_card(email_id: int, payload: EmailSnipRequest):
    try:
        drafts = preview_snip_email(email_id, payload.split_offsets)
    except SnipError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if drafts is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return drafts


@router.delete("/api/emails/{email_id}")
def delete_email(email_id: int):
    if not email_repo.soft_delete_email(email_id):
        raise HTTPException(status_code=404, detail="Email not found")
    return {"ok": True, "trashed": True}


@router.post("/api/emails/{email_id}/restore")
def restore_email(email_id: int):
    email = email_repo.restore_email(email_id)
    if not email:
        raise HTTPException(status_code=400, detail="Email is not restorable")
    return email


@router.post("/api/emails/{email_id}/source/open")
def open_email_source(email_id: int):
    source = email_repo.get_email_source(email_id)
    if not source:
        raise HTTPException(status_code=404, detail="Email not found")
    if not source["source_openable"]:
        raise HTTPException(status_code=400, detail="This email source is not openable")

    path = source_store.resolve_source(source)
    if path is None:
        # The original moved (or was never captured). Signal the UI to offer a
        # relocate action rather than a dead 404.
        raise HTTPException(
            status_code=409,
            detail={"detail": "Source file not found", "reason": "source_moved"},
        )
    # Validate against the ORIGINAL source filename's suffix, not the display
    # label: derived rows (quoted/snip/selection) keep the parent's clean
    # source_file but decorate source_file_display (" snip #1", " quoted #1",
    # " selection"), which would make Path(...).suffix read e.g. ".pdf snip #1"
    # and spuriously 403 an openable .pdf/.docx. Managed-store blobs are
    # content-addressed and carry no extension of their own, so the suffix (and
    # the openable copy's extension) must come from this logical name.
    origin_name = source["source_file"] or source["source_file_display"] or ""
    if Path(origin_name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=403, detail="Only .eml, .msg, .pdf, and .docx sources can be opened")
    open_path = source_store.openable_copy(path, origin_name)

    try:
        os.startfile(str(open_path))  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise HTTPException(status_code=501, detail="Opening source files is only supported on Windows") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not open source file: {exc}") from exc
    return {"ok": True}


@router.patch("/api/cases/{case_id}/chain-order")
def patch_chain_order(case_id: int, payload: ChainOrderUpdate):
    if not ordering_repo.update_manual_chain_order(case_id, payload.email_ids):
        raise HTTPException(status_code=400, detail="Chain order could not be saved")
    return email_repo.list_emails(case_id, view="thread")


@router.patch("/api/cases/{case_id}/email-order")
def patch_chronology_order(case_id: int, payload: ChronologyOrderUpdate):
    if not ordering_repo.update_manual_chronology_order(case_id, payload.email_ids):
        raise HTTPException(status_code=400, detail="Chronology order could not be saved")
    return email_repo.list_emails(case_id, view="chrono")


def clean_address_list(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value.strip()]


def normalize_email_update_date(email_id: int, changes: dict) -> None:
    raw_value = changes.get("date_utc")
    if raw_value is None or not str(raw_value).strip():
        changes["date_utc"] = None
        changes["date_raw"] = None
        return

    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT c.default_tz
            FROM emails e
            JOIN cases c ON c.id = e.case_id
            WHERE e.id = ?
            """,
            (email_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Email not found")

    raw_text = str(raw_value).strip()
    parsed = to_utc(raw_text, row["default_tz"] or "UTC")
    if not parsed:
        raise HTTPException(status_code=400, detail="Date could not be parsed")
    changes["date_utc"] = parsed
    changes["date_raw"] = raw_text
