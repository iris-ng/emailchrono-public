from fastapi import APIRouter, HTTPException

from ..repos import cases as case_repo
from ..models.schemas import CaseCreate, CasePermanentDelete, CaseUpdate
from ..services.dates import is_valid_timezone
from ..services.ingest import recompute_case_dates

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.get("")
def list_cases():
    return case_repo.list_cases()


@router.post("")
def create_case(payload: CaseCreate):
    tz = payload.default_tz or "UTC"
    if not is_valid_timezone(tz):
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz}")
    return case_repo.create_case(payload.name, tz)


@router.patch("/{case_id}")
def update_case(case_id: int, payload: CaseUpdate):
    if payload.default_tz is not None and not is_valid_timezone(payload.default_tz):
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {payload.default_tz}")
    updated = case_repo.update_case(case_id, name=payload.name, default_tz=payload.default_tz)
    if not updated:
        raise HTTPException(status_code=404, detail="Case not found")
    # Re-derive dates so naive timestamps reflect the new matter timezone.
    if payload.default_tz is not None:
        recompute_case_dates(case_id, payload.default_tz)
        updated = case_repo.get_case(case_id)
    return updated


# Declared before "/{case_id}" so the literal path is matched first.
@router.get("/trash")
def list_trash():
    return case_repo.list_deleted_cases()


@router.get("/{case_ref}")
def get_case(case_ref: str):
    # Accepts the stable public_id (used in URLs) or the legacy integer id.
    case = case_repo.get_case_by_ref(case_ref)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get("/{case_id}/audit")
def list_case_audit(case_id: int):
    if not case_repo.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    return case_repo.list_audit_events(case_id)


@router.delete("/{case_id}")
def delete_case(case_id: int):
    # Soft delete: move the case to trash. It can be recovered or, only with an
    # explicit confirmation, permanently removed.
    if not case_repo.soft_delete_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    return {"ok": True, "trashed": True}


@router.post("/{case_id}/restore")
def restore_case(case_id: int):
    if not case_repo.restore_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found in trash")
    return {"ok": True}


@router.post("/{case_id}/permanent-delete")
def permanently_delete_case(case_id: int, payload: CasePermanentDelete):
    case = case_repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if payload.name.strip() != (case["name"] or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Matter name does not match. Type the exact name to confirm.",
        )
    case_repo.delete_case(case_id)
    return {"ok": True, "deleted": True}
