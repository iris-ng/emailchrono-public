from typing import List

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from ..config import MAX_INGEST_BATCH_BYTES, MAX_INGEST_FILE_BYTES
from .. import db
from ..repos import case_folders as case_folder_repo
from ..repos import cases as case_repo
from ..repos import ingest_jobs as ingest_job_repo
from ..models.schemas import FolderIngestRequest
from ..services.ingest import (
    PendingUpload,
    create_folder_job,
    create_upload_job,
    run_folder_job,
    run_upload_job,
)

router = APIRouter(prefix="/api/cases/{case_id}/ingest", tags=["ingest"])


async def _read_bounded_upload(upload: UploadFile) -> PendingUpload:
    filename = upload.filename or "message.eml"
    if upload.size is not None and upload.size > MAX_INGEST_FILE_BYTES:
        return PendingUpload(
            filename,
            b"",
            skip_error=f"File exceeds {MAX_INGEST_FILE_BYTES} byte ingest limit.",
        )
    content = await upload.read(MAX_INGEST_FILE_BYTES + 1)
    if len(content) > MAX_INGEST_FILE_BYTES:
        return PendingUpload(
            filename,
            b"",
            skip_error=f"File exceeds {MAX_INGEST_FILE_BYTES} byte ingest limit.",
        )
    return PendingUpload(filename, content)


@router.post("")
async def ingest_files(
    case_id: int,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    tag_ids: List[int] = Form(default=[]),
    contains_cjk: bool = Form(default=False),
):
    try:
        uploads = []
        total = 0
        for upload in files:
            pending = await _read_bounded_upload(upload)
            total += len(pending.content)
            if total > MAX_INGEST_BATCH_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload batch exceeds {MAX_INGEST_BATCH_BYTES} byte limit.",
                )
            uploads.append(pending)
        job, default_tz = create_upload_job(case_id, uploads, contains_cjk)
        background_tasks.add_task(
            run_upload_job, case_id, job["id"], uploads, default_tz, tag_ids, contains_cjk
        )
        return job
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/folder")
def ingest_folder_path(case_id: int, payload: FolderIngestRequest, background_tasks: BackgroundTasks):
    try:
        job, paths, default_tz = create_folder_job(
            case_id, payload.folder_path, payload.recursive, contains_cjk=payload.contains_cjk
        )
        background_tasks.add_task(
            run_folder_job, case_id, job["id"], paths, default_tz, payload.tag_ids, payload.contains_cjk
        )
        return job
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/folders")
def list_tracked_folders(case_id: int):
    return case_folder_repo.list_case_folders(case_id)


@router.post("/folder/{folder_id}/refresh")
def refresh_folder(case_id: int, folder_id: int, background_tasks: BackgroundTasks):
    with db.get_conn() as conn:
        folder = case_folder_repo.get_case_folder(conn, case_id, folder_id)
        case = case_repo.get_case_by_id(conn, case_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Tracked folder not found")
    # A refresh has no UI checkbox, so inherit the case's sticky CJK flag.
    contains_cjk = bool(case and case.get("has_cjk_content"))
    try:
        job, paths, default_tz = create_folder_job(
            case_id, folder["folder_path"], folder["recursive"], skip_existing=True,
            contains_cjk=contains_cjk,
        )
        background_tasks.add_task(
            run_folder_job, case_id, job["id"], paths, default_tz, None, contains_cjk
        )
        return job
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("")
def list_ingest_jobs(case_id: int):
    return ingest_job_repo.list_ingest_jobs(case_id)


@router.get("/{job_id}")
def get_ingest_job(case_id: int, job_id: int):
    job = ingest_job_repo.get_ingest_job(case_id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingest job not found")
    return job
