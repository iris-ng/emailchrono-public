from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AttachmentParseResult:
    filename: str
    mime: str
    content: bytes
    content_id: Optional[str] = None
    is_inline: bool = False
    # True when this attachment is itself an email message (message/rfc822 part,
    # embedded .msg, or an .eml/.msg file attachment). Such attachments are parsed
    # into first-class source_kind='attached' timeline rows; the raw bytes are still
    # kept as a downloadable attachment.
    is_email: bool = False
    # Embedded .msg attachments are parsed eagerly (while the parent .msg file is
    # still open) into an EmailParseResult and stashed here, because extract_msg
    # invalidates child message objects once the parent is closed. nested_email
    # returns this directly instead of re-parsing from bytes.
    embedded_parsed: object = None

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass
class EmailParseResult:
    source_file: str
    source_file_display: str
    message_id: Optional[str]
    in_reply_to: Optional[str]
    references: List[str]
    from_addr: str
    to: List[str]
    cc: List[str]
    date_utc: Optional[str]
    date_raw: Optional[str]
    subject: str
    body_text: str
    body_html_raw: str
    body_html_sanitized: str
    body_format: str
    parse_confidence: str
    flags: List[str] = field(default_factory=list)
    source_kind: str = "standalone"
    parent_email_id: Optional[int] = None
    chain_source_id: Optional[int] = None
    chain_position: int = 0
    manual_chain_order: Optional[int] = None
    source_import_mode: str = "upload"
    source_openable: bool = False
    source_size: Optional[int] = None
    source_mtime: Optional[str] = None
    source_sha256: Optional[str] = None
    # SHA-256 key into the managed content-addressed source store, set when the
    # original bytes were captured (uploads/folder scans when source capture is on).
    source_blob_sha256: Optional[str] = None
    attachments: List[AttachmentParseResult] = field(default_factory=list)
    boundary_method: str = "mime"
    boundary_evidence: List[str] = field(default_factory=list)
    relation_confidence: str = "high"
    # Body text as originally parsed, before boilerplate stripping. Preserved in
    # raw_json so disclaimer removal stays reversible/traceable.
    body_text_original: Optional[str] = None
    # Outlook/Exchange conversation grouping (absent for non-Outlook mail).
    # conversation_index: base64 PR_CONVERSATION_INDEX / Thread-Index, a stable
    # per-conversation key independent of Message-ID/References. conversation_topic:
    # the client-stripped thread subject (PR_CONVERSATION_TOPIC / Thread-Topic).
    conversation_index: Optional[str] = None
    conversation_topic: Optional[str] = None


class DocumentIngestError(Exception):
    """Base for non-fatal reasons a document was not ingested as an email.

    ingest records these as a *skipped* file (not a parse failure) so a mixed
    folder of PDFs/.docx never marks the whole job failed.
    """


class NotAnEmailError(DocumentIngestError):
    """The document does not open with an email header cluster."""


class EmptyDocumentError(DocumentIngestError):
    """No extractable text (e.g. a scanned / image-only PDF). No OCR is attempted."""
