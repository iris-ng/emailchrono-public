import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from .. import db
from ..services.text_norm import json_dumps, json_loads, row_to_dict


def create_ingest_job(
    conn: sqlite3.Connection,
    case_id: int,
    total_files: int,
    contains_cjk: bool = False,
) -> int:
    now = db.utc_now()
    cur = conn.execute(
        """
        INSERT INTO ingest_jobs
          (case_id, status, total_files, processed_files, failed_files, started_at,
           contains_cjk)
        VALUES (?, 'running', ?, 0, 0, ?, ?)
        """,
        (case_id, total_files, now, int(contains_cjk)),
    )
    return int(cur.lastrowid)


def update_ingest_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status: Optional[str] = None,
    processed_delta: int = 0,
    failed_delta: int = 0,
    error: Optional[Dict[str, Any]] = None,
) -> None:
    updates = []
    params: List[Any] = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
        if status in {"completed", "failed"}:
            updates.append("finished_at = ?")
            params.append(db.utc_now())
    if processed_delta:
        updates.append("processed_files = processed_files + ?")
        params.append(processed_delta)
    if failed_delta:
        updates.append("failed_files = failed_files + ?")
        params.append(failed_delta)
    if error is not None:
        updates.append("error_json = ?")
        params.append(json_dumps(error))
    if not updates:
        return
    params.append(job_id)
    conn.execute(f"UPDATE ingest_jobs SET {', '.join(updates)} WHERE id = ?", params)


def add_ingest_file(
    conn: sqlite3.Connection,
    job_id: int,
    source_file_display: str,
    status: str,
    email_id: Optional[int] = None,
    error: Optional[str] = None,
    warnings: Optional[Sequence[str]] = None,
    source_import_mode: str = "upload",
    source_size: Optional[int] = None,
    source_mtime: Optional[str] = None,
    source_sha256: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO ingest_files
          (job_id, source_file_display, status, email_id, error, warning_json,
           source_import_mode, source_size, source_mtime, source_sha256, doc_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            source_file_display,
            status,
            email_id,
            error,
            json_dumps(list(warnings or [])),
            source_import_mode,
            source_size,
            source_mtime,
            source_sha256,
            doc_id,
            db.utc_now(),
        ),
    )


def get_ingest_job(case_id: int, job_id: int) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ingest_jobs WHERE case_id = ? AND id = ?",
            (case_id, job_id),
        ).fetchone()
        if not row:
            return None
        job = row_to_dict(row)
        files = conn.execute(
            "SELECT * FROM ingest_files WHERE job_id = ? ORDER BY id",
            (job_id,),
        ).fetchall()
        job["files"] = [row_to_dict(file_row) for file_row in files]
        for file_item in job["files"]:
            file_item["warning_json"] = json_loads(file_item.get("warning_json"), [])
        job["error_json"] = json_loads(job.get("error_json"), None)
        return job


def list_ingest_jobs(case_id: int) -> List[Dict[str, Any]]:
    """All ingest jobs for a case (newest first), each with its files."""
    with db.get_conn() as conn:
        job_rows = conn.execute(
            "SELECT * FROM ingest_jobs WHERE case_id = ? ORDER BY id DESC",
            (case_id,),
        ).fetchall()
        jobs = []
        for row in job_rows:
            job = row_to_dict(row)
            files = conn.execute(
                "SELECT * FROM ingest_files WHERE job_id = ? ORDER BY id",
                (job["id"],),
            ).fetchall()
            job["files"] = [row_to_dict(file_row) for file_row in files]
            for file_item in job["files"]:
                file_item["warning_json"] = json_loads(file_item.get("warning_json"), [])
            job["error_json"] = json_loads(job.get("error_json"), None)
            jobs.append(job)
        return jobs
