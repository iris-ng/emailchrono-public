from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CaseCreate(BaseModel):
    name: str
    default_tz: Optional[str] = None


class CaseUpdate(BaseModel):
    name: Optional[str] = None
    default_tz: Optional[str] = None


class CasePermanentDelete(BaseModel):
    # The user must re-type the matter name to confirm an irreversible delete.
    name: str


class CaseOut(BaseModel):
    id: int
    public_id: str
    name: str
    created_at: str
    updated_at: str
    email_count: int = 0
    has_cjk_content: bool = False


class AttachmentOut(BaseModel):
    id: int
    email_id: int
    filename: str
    mime: str
    size: int
    content_id: Optional[str] = None
    is_inline: bool = False
    created_at: str


class TagOut(BaseModel):
    id: int
    case_id: int
    name: str
    color: str
    created_at: str


class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class EmailTagsUpdate(BaseModel):
    email_ids: List[int]
    tag_ids: List[int]


class EmailOut(BaseModel):
    id: int
    case_id: int
    doc_id: Optional[str] = None
    source_file_display: str
    source_import_mode: str = "upload"
    source_openable: bool = False
    source_size: Optional[int] = None
    source_mtime: Optional[str] = None
    source_sha256: Optional[str] = None
    ingest_job_id: Optional[int] = None
    derived_from_attachment_id: Optional[int] = None
    message_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: List[str] = []
    from_addr: str
    to: List[str] = []
    cc: List[str] = []
    date_utc: Optional[str] = None
    date_raw: Optional[str] = None
    subject: str
    body_text: str
    body_html_raw: str
    body_html_sanitized: str
    body_format: str
    thread_id: Optional[str] = None
    parse_confidence: str
    source_kind: str
    parent_email_id: Optional[int] = None
    chain_source_id: Optional[int] = None
    chain_position: int = 0
    manual_chain_order: Optional[int] = None
    manual_chrono_order: Optional[int] = None
    chain_date_conflict: bool = False
    notes: str = ""
    important: bool = False
    user_edited: bool
    raw_json: Dict[str, Any] = {}
    created_at: str
    deleted_at: Optional[str] = None
    suspected_duplicate_count: int = 0
    flags: List[str] = []
    attachments: List[AttachmentOut] = []
    tags: List[TagOut] = []
    boundary_method: str = "mime"
    boundary_evidence: List[str] = []
    relation_confidence: str = "high"
    relation_thread_id: str = ""
    relation_parent_id: Optional[int] = None
    relation_source_id: int = 0
    relation_refs: Dict[str, Any] = {}


class EmailUpdate(BaseModel):
    from_addr: Optional[str] = None
    to: Optional[List[str]] = None
    cc: Optional[List[str]] = None
    date_utc: Optional[str] = None
    subject: Optional[str] = None
    body_text: Optional[str] = None
    notes: Optional[str] = None
    important: Optional[bool] = None


class EmailCreate(BaseModel):
    from_addr: str = ""
    to: List[str] = Field(default_factory=list)
    cc: List[str] = Field(default_factory=list)
    date_raw: Optional[str] = None
    subject: str = ""
    body_text: str = ""
    notes: str = ""
    important: bool = False


class EmailSnipPartDraft(BaseModel):
    part_index: int
    from_addr: str = ""
    to: List[str] = Field(default_factory=list)
    cc: List[str] = Field(default_factory=list)
    date_raw: Optional[str] = None
    subject: str = ""
    body_text: str = ""
    notes: str = ""
    important: bool = False
    approved: bool = False


class EmailSnipRequest(BaseModel):
    split_offsets: List[int] = Field(default_factory=list)
    parts: List[EmailSnipPartDraft] = Field(default_factory=list)


class SourceCardCreate(BaseModel):
    source_field: str
    start_offset: int
    end_offset: int
    subject: Optional[str] = None
    notes: str = ""
    important: bool = False


class SourceCardSelection(BaseModel):
    source_email_id: int
    source_field: str
    start_offset: int
    end_offset: int


class SourceCardGroupCreate(BaseModel):
    selections: List[SourceCardSelection] = Field(default_factory=list)
    subject: Optional[str] = None
    notes: str = ""
    important: bool = False


class DuplicateCandidateOut(BaseModel):
    id: int
    case_id: int
    email_a_id: int
    email_b_id: int
    score: float
    reasons: List[Dict[str, Any]] = []
    status: str
    canonical_email_id: Optional[int] = None
    duplicate_email_id: Optional[int] = None
    created_at: str
    updated_at: str
    decided_at: Optional[str] = None
    email_a: Optional[EmailOut] = None
    email_b: Optional[EmailOut] = None


class DuplicateCandidateUpdate(BaseModel):
    status: str
    canonical_email_id: Optional[int] = None
    duplicate_email_id: Optional[int] = None


class DuplicateClusterResolve(BaseModel):
    canonical_email_id: int
    duplicate_email_ids: List[int]


class ChainOrderUpdate(BaseModel):
    email_ids: List[int]


class ChronologyOrderUpdate(BaseModel):
    email_ids: List[int]


class FolderIngestRequest(BaseModel):
    folder_path: str
    recursive: bool = True
    tag_ids: List[int] = Field(default_factory=list)
    contains_cjk: bool = False


class RelocateSourcesRequest(BaseModel):
    new_root: str


class IngestFileOut(BaseModel):
    id: int
    job_id: int
    source_file_display: str
    status: str
    email_id: Optional[int] = None
    error: Optional[str] = None
    warning_json: List[str] = []
    source_import_mode: str = "upload"
    source_size: Optional[int] = None
    source_mtime: Optional[str] = None
    source_sha256: Optional[str] = None
    doc_id: Optional[str] = None
    created_at: str


class IngestJobOut(BaseModel):
    id: int
    case_id: int
    status: str
    total_files: int
    processed_files: int
    failed_files: int
    started_at: str
    finished_at: Optional[str] = None
    error_json: Optional[Dict[str, Any]] = None
    contains_cjk: bool = False
    files: List[IngestFileOut] = []
