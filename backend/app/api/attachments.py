from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..repos import attachments as attachment_repo
from ..config import ATTACHMENTS_DIR

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


@router.get("/{attachment_id}")
def download_attachment(attachment_id: int):
    attachment = attachment_repo.get_attachment(attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    disk_path = attachment["disk_path"] or ""
    stored = Path(disk_path)
    # disk_path is stored relative to ATTACHMENTS_DIR (migration 023). Legacy rows
    # that escaped the backfill may still hold an absolute path -- honor both.
    path = (stored if stored.is_absolute() else ATTACHMENTS_DIR / stored).resolve()
    root = ATTACHMENTS_DIR.resolve()
    # `is_relative_to` is robust where the old `root not in path.parents` test was
    # brittle: on Windows, long paths / casing / extended-length (\\?\) prefixes
    # could make the exact-object `.parents` membership check fail for a file that
    # genuinely lives under ATTACHMENTS_DIR, spuriously returning 403.
    if not path.is_relative_to(root):
        raise HTTPException(status_code=403, detail="Attachment path is outside data directory")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file not found")
    return FileResponse(path, filename=attachment["filename"], media_type=attachment["mime"])
