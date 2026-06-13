"""Content-addressed store for original email source bytes.

Originals live under ``SOURCES_DIR/<sha[:2]>/<sha>`` -- sharded by the first two
hex chars to keep any one directory small, addressed by the SHA-256 of the bytes
so identical uploads dedupe for free. Paths are returned relative to SOURCES_DIR
so they survive a data-dir move; ``resolve_source`` re-roots them at read time.

This is the single place that knows how to find an email's original bytes,
whether they were captured into the managed store (uploads, Phase 3; imports,
Phase 2) or still live at a folder-scan path on disk.
"""

import hashlib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional

from ..config import SOURCES_DIR

_RELOCATE_SUFFIXES = {".eml", ".msg", ".pdf", ".docx"}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def is_valid_sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value or ""))


def relative_path_for(sha: str) -> str:
    if not is_valid_sha256(sha):
        raise ValueError("Invalid source blob hash")
    sha = sha.lower()
    return f"{sha[:2]}/{sha}"


def store_source(content: bytes, sha: str) -> str:
    """Persist ``content`` under its SHA-256 and return the SOURCES_DIR-relative
    path. Idempotent: identical bytes (same sha) are written once."""
    rel = relative_path_for(sha)
    target = SOURCES_DIR / rel
    root = SOURCES_DIR.resolve()
    resolved = target.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Invalid source blob path")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return rel


def managed_path(sha: str) -> Path:
    """Absolute path where ``sha`` would live in the managed store."""
    return SOURCES_DIR / relative_path_for(sha)


def resolve_source(email_row: Mapping[str, Any]) -> Optional[Path]:
    """Resolve an email's original source file to a real path, or None.

    Resolution order:
      (a) managed copy, if ``source_blob_sha256`` is set and present on disk;
      (b) the stored ``source_file`` path for folder-scan rows, if it still
          exists (upload-mode ``source_file`` is a bare filename, not a path,
          so it is never resolved as one);
      (c) None -- the caller should offer to relocate.
    """
    sha = email_row.get("source_blob_sha256")
    if sha:
        managed = managed_path(sha)
        if managed.exists():
            return managed

    if email_row.get("source_import_mode") == "local_folder":
        source_file = email_row.get("source_file")
        if source_file:
            candidate = Path(source_file)
            if candidate.exists() and candidate.is_file():
                return candidate

    return None


def openable_copy(resolved: Path, display_name: str) -> Path:
    """Return a path whose extension matches ``display_name`` so the OS handler
    opens it correctly.

    Managed-store blobs are content-addressed and have no extension; copy them
    once to a temp file carrying the original suffix. Folder-scan paths already
    have the right extension and are returned unchanged.
    """
    suffix = Path(display_name).suffix
    if suffix and resolved.suffix.lower() == suffix.lower():
        return resolved
    tmp_dir = Path(tempfile.gettempdir()) / "emailchrono_sources"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / f"{resolved.name}{suffix}"
    if not target.exists():
        shutil.copyfile(resolved, target)
    return target


def relocate_case_sources(case_id: int, new_root: str) -> int:
    """Re-link a case's emails to moved evidence files under ``new_root``.

    Matches by ``source_sha256`` (authoritative content hash; filename is only a
    hint). For each match the original bytes are folded into the managed store
    (keyed by that sha, which equals the file's content hash) and the row is
    marked openable. Returns the count of re-linked emails. Records a
    ``case.sources_relocated`` audit event and bumps ``cases.updated_at``.
    """
    root = Path(new_root)
    if not root.exists() or not root.is_dir():
        raise ValueError("Folder not found")

    # Index candidate files under the new root by content hash (first wins).
    sha_to_path: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.suffix.lower() in _RELOCATE_SUFFIXES and path.is_file():
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            sha_to_path.setdefault(digest, path)

    from .. import db
    from .audit import record_audit_event

    relinked = 0
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, source_sha256 FROM emails
            WHERE case_id = ? AND source_sha256 IS NOT NULL AND deleted_at IS NULL
            """,
            (case_id,),
        ).fetchall()
        for row in rows:
            match = sha_to_path.get(row["source_sha256"])
            if match is None:
                continue
            store_source(match.read_bytes(), row["source_sha256"])
            conn.execute(
                """
                UPDATE emails
                SET source_file = ?, source_openable = 1, source_blob_sha256 = ?
                WHERE id = ?
                """,
                (str(match), row["source_sha256"], row["id"]),
            )
            relinked += 1
        if relinked:
            record_audit_event(
                conn,
                case_id=case_id,
                action="case.sources_relocated",
                entity_type="case",
                entity_id=case_id,
                metadata={"new_root": str(root), "relinked": relinked},
            )
            conn.execute(
                "UPDATE cases SET updated_at = ? WHERE id = ?", (db.utc_now(), case_id)
            )
    return relinked
