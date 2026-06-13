from fastapi import APIRouter, HTTPException

from ..repos import cases as case_repo
from ..repos import tags as tag_repo
from ..models.schemas import EmailTagsUpdate, TagCreate, TagUpdate

router = APIRouter(tags=["tags"])


@router.get("/api/cases/{case_id}/tags")
def list_tags(case_id: int):
    if not case_repo.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    return tag_repo.list_tags(case_id)


@router.post("/api/cases/{case_id}/tags")
def create_tag(case_id: int, payload: TagCreate):
    tag = tag_repo.create_tag(case_id, payload.name, payload.color)
    if not tag:
        raise HTTPException(status_code=400, detail="Tag name is required, or the case does not exist")
    return tag


@router.patch("/api/tags/{tag_id}")
def update_tag(tag_id: int, payload: TagUpdate):
    tag = tag_repo.update_tag(tag_id, name=payload.name, color=payload.color)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


@router.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int):
    if not tag_repo.delete_tag(tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"ok": True, "deleted": True}


@router.post("/api/cases/{case_id}/emails/tags")
def attach_tags(case_id: int, payload: EmailTagsUpdate):
    if not case_repo.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    added = tag_repo.add_tags_to_emails(case_id, payload.email_ids, payload.tag_ids)
    return {"ok": True, "added": added}


@router.delete("/api/cases/{case_id}/emails/tags")
def detach_tags(case_id: int, payload: EmailTagsUpdate):
    if not case_repo.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    removed = tag_repo.remove_tags_from_emails(case_id, payload.email_ids, payload.tag_ids)
    return {"ok": True, "removed": removed}
