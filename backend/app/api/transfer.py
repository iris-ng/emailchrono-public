from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from ..models.schemas import RelocateSourcesRequest
from ..services import source_store, transfer
from ..services.transfer import ExportError, ImportError_

router = APIRouter(tags=["transfer"])


def _safe_filename(name: str) -> str:
    cleaned = "".join(ch for ch in (name or "") if ch.isalnum() or ch in {" ", "_", "-"}).strip()
    return cleaned or "case"


@router.get("/api/cases/{case_id}/export")
def export_case(case_id: int):
    try:
        data = transfer.export_case(case_id)
    except ExportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    filename = f"{_safe_filename('case')}-{case_id}.ecz"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/import/preview")
async def import_preview(file: UploadFile = File(...)):
    data = await file.read()
    try:
        return transfer.preview_bundle(data)
    except ImportError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/import")
async def import_case(file: UploadFile = File(...)):
    data = await file.read()
    try:
        return transfer.import_bundle(data)
    except ImportError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/cases/{case_id}/relocate-sources")
def relocate_sources(case_id: int, payload: RelocateSourcesRequest):
    try:
        relinked = source_store.relocate_case_sources(case_id, payload.new_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"relinked": relinked}
