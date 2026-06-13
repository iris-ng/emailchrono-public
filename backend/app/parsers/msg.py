import base64
from datetime import datetime, timezone
from email.parser import Parser
from email.policy import default
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, List, Optional

import extract_msg
from charset_normalizer import from_bytes

from .base import AttachmentParseResult, EmailParseResult
from ..services.dates import to_utc
from ..services.sanitize import sanitize_html


def decode_best(value: bytes) -> str:
    """Decode bytes from a legacy .msg property whose charset is unknown.

    Modern .msg files expose Unicode MAPI properties (already ``str``), but older
    files store body/HTML bytes in the originating code page (e.g. GBK, Big5,
    Shift-JIS). Force-decoding those as UTF-8 yields mojibake for CJK text, so we
    let charset-normalizer detect the encoding and fall back to UTF-8 with
    replacement only when detection fails."""
    try:
        best = from_bytes(value).best()
    except Exception:
        best = None
    if best is not None:
        return str(best)
    return value.decode("utf-8", errors="replace")


def parse_msg_bytes(content: bytes, source_file_display: str, default_tz: str = "UTC") -> EmailParseResult:
    with NamedTemporaryFile(suffix=".msg", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        return parse_msg_path(tmp_path, source_file_display, default_tz)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except TypeError:
            if tmp_path.exists():
                tmp_path.unlink()


def parse_msg_path(
    path: Path, source_file_display: Optional[str] = None, default_tz: str = "UTC"
) -> EmailParseResult:
    msg = extract_msg.Message(str(path))
    try:
        display = source_file_display or path.name
        return parse_msg_message(msg, display, default_tz)
    finally:
        msg.close()


def parse_msg_message(msg: Any, display: str, default_tz: str = "UTC") -> EmailParseResult:
    """Parse an already-open extract_msg message into an EmailParseResult.

    Shared by parse_msg_path (top-level files) and extract_attachments (embedded
    .msg messages, which arrive as live message objects, not a path). The caller
    owns the message lifecycle; this function does not close it.
    """
    flags: List[str] = []
    headers = parse_transport_headers(getattr(msg, "header", None) or getattr(msg, "headerText", None))

    message_id = first_text(
        getattr(msg, "messageId", None),
        headers.get("Message-ID"),
    )
    if not message_id:
        flags.append("missing_message_id")

    date_raw = first_text(
        getattr(msg, "date", None),
        getattr(msg, "receivedTime", None),
        headers.get("Date"),
    )
    date_utc = normalize_msg_date(
        [
            getattr(msg, "parsedDate", None),
            getattr(msg, "date", None),
            getattr(msg, "receivedTime", None),
        ],
        default_tz,
    )
    if not date_utc:
        flags.append("missing_date")

    body_text = first_text(getattr(msg, "body", None)) or ""
    body_html_raw = decode_html_body(getattr(msg, "htmlBody", None))
    body_html_sanitized = sanitize_html(body_html_raw)
    if body_html_raw and body_html_sanitized != body_html_raw:
        flags.append("html_sanitized")

    body_format = "html" if body_html_raw else "text"
    if not body_text and body_html_sanitized:
        body_text = html_to_text(body_html_sanitized)

    attachments = extract_attachments(getattr(msg, "attachments", []), default_tz)

    # extract_msg exposes the conversation properties only as raw MAPI streams,
    # not as attributes; the transport Thread-Index / Thread-Topic headers are the
    # fallback when the .msg has no stored property (e.g. some sent items).
    conversation_index = msg_conversation_index(msg) or first_text(headers.get("Thread-Index"))
    conversation_topic = first_text(
        msg_string_stream(msg, "__substg1.0_0070"),
        headers.get("Thread-Topic"),
    )

    parse_confidence = "low" if "missing_date" in flags else "high"
    if "missing_message_id" in flags and parse_confidence == "high":
        parse_confidence = "med"

    return EmailParseResult(
        source_file=display,
        source_file_display=display,
        message_id=message_id,
        in_reply_to=first_text(getattr(msg, "inReplyTo", None), headers.get("In-Reply-To")),
        references=parse_references(headers.get("References")),
        from_addr=first_text(getattr(msg, "sender", None), headers.get("From")) or "",
        to=split_recipients(first_text(getattr(msg, "to", None), headers.get("To"))),
        cc=split_recipients(first_text(getattr(msg, "cc", None), headers.get("Cc"))),
        date_utc=date_utc,
        date_raw=date_raw,
        subject=first_text(getattr(msg, "subject", None), headers.get("Subject")) or "(no subject)",
        body_text=body_text.strip(),
        body_html_raw=body_html_raw,
        body_html_sanitized=body_html_sanitized,
        body_format=body_format,
        parse_confidence=parse_confidence,
        flags=dedupe(flags),
        attachments=attachments,
        conversation_index=conversation_index,
        conversation_topic=conversation_topic,
    )


def msg_string_stream(msg: Any, stream_id: str) -> Optional[str]:
    """Read a Unicode MAPI string stream (e.g. PR_CONVERSATION_TOPIC) if exposed."""
    getter = getattr(msg, "getStringStream", None)
    if not callable(getter):
        return None
    try:
        value = getter(stream_id)
    except Exception:
        return None
    return value if isinstance(value, str) and value else None


def msg_conversation_index(msg: Any) -> Optional[str]:
    """Base64 PR_CONVERSATION_INDEX (tag 0x0071, binary), or None.

    Returned base64 so it lines up with the transport Thread-Index header form
    and with what text_norm.conversation_index_root expects to decode.
    """
    getter = getattr(msg, "getPropertyVal", None)
    if not callable(getter):
        return None
    try:
        raw = getter("00710102")
    except Exception:
        return None
    if isinstance(raw, (bytes, bytearray)) and raw:
        return base64.b64encode(bytes(raw)).decode("ascii")
    return None


def parse_transport_headers(value: Any) -> dict:
    text = first_text(value)
    if not text:
        return {}
    parsed = Parser(policy=default).parsestr(text)
    return {key: parsed.get(key) for key in parsed.keys()}


def decode_html_body(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, bytes):
        return decode_best(value)
    return str(value)


def normalize_msg_date(values: Iterable[Any], default_tz: str = "UTC") -> Optional[str]:
    for value in values:
        if not value:
            continue
        iso = to_utc(value, default_tz)
        if iso:
            return iso
    return None


def extract_attachments(values: Iterable[Any], default_tz: str = "UTC") -> List[AttachmentParseResult]:
    attachments: List[AttachmentParseResult] = []
    for index, attachment in enumerate(values, start=1):
        filename = first_text(
            getattr(attachment, "longFilename", None),
            getattr(attachment, "shortFilename", None),
            getattr(attachment, "filename", None),
        )
        content_id = first_text(getattr(attachment, "cid", None), getattr(attachment, "contentId", None))

        # An embedded message arrives as a live extract_msg message object, not
        # bytes, so attachment_bytes() returns None and it was silently dropped.
        # Parse it eagerly here (the parent file is still open) into its own row.
        embedded = embedded_message(attachment)
        if embedded is not None:
            display = filename or f"attached-message-{index}.msg"
            try:
                embedded_parsed = parse_msg_message(embedded, display, default_tz)
            except Exception:
                embedded_parsed = None
            if embedded_parsed is not None:
                attachments.append(
                    AttachmentParseResult(
                        filename=display,
                        mime="application/vnd.ms-outlook",
                        content=embedded_bytes(embedded),
                        content_id=content_id.strip("<>") if content_id else None,
                        is_inline=False,
                        is_email=True,
                        embedded_parsed=embedded_parsed,
                    )
                )
                continue

        data = attachment_bytes(attachment)
        if data is None:
            continue
        resolved_name = filename or f"attachment-{index}"
        mime = first_text(getattr(attachment, "mimetype", None), getattr(attachment, "mimeType", None))
        attachments.append(
            AttachmentParseResult(
                filename=resolved_name,
                mime=mime or "application/octet-stream",
                content=data,
                content_id=content_id.strip("<>") if content_id else None,
                is_inline=bool(content_id),
                # A file attachment that is itself an email (e.g. a forwarded
                # "message.eml"/"note.msg") becomes its own timeline row too.
                is_email=is_email_filename(resolved_name),
            )
        )
    return attachments


def embedded_message(attachment: Any) -> Optional[Any]:
    """Return the embedded extract_msg message object for an attachment, or None.

    Embedded messages expose their content as a MSGFile/Message object on .data
    (rather than raw bytes). We match on that type, falling back to the attachment
    type enum when the class is not importable.
    """
    data = getattr(attachment, "data", None)
    msg_file_cls = getattr(extract_msg, "MSGFile", None)
    if msg_file_cls is not None and isinstance(data, msg_file_cls):
        return data
    att_type = getattr(attachment, "type", None)
    type_name = getattr(att_type, "name", None) or (str(att_type) if att_type is not None else "")
    if "msg" in type_name.lower() and hasattr(data, "attachments"):
        return data
    return None


def embedded_bytes(embedded: Any) -> bytes:
    """Best-effort raw bytes of an embedded .msg, kept as a downloadable attachment.

    Not all extract_msg versions can re-serialize an embedded message; if export
    is unavailable the parsed timeline row is still created, only the raw download
    is empty.
    """
    method = getattr(embedded, "exportBytes", None)
    if callable(method):
        try:
            value = method()
            if isinstance(value, bytes):
                return value
        except Exception:
            pass
    return b""


def is_email_filename(filename: Optional[str]) -> bool:
    if not filename:
        return False
    return filename.strip().lower().endswith((".eml", ".msg"))


def attachment_bytes(attachment: Any) -> Optional[bytes]:
    for attr in ("data", "content"):
        value = getattr(attachment, attr, None)
        if isinstance(value, bytes):
            return value
    for method_name in ("getData", "exportBytes"):
        method = getattr(attachment, method_name, None)
        if not callable(method):
            continue
        try:
            value = method()
        except Exception:
            continue
        if isinstance(value, bytes):
            return value
    return None


def first_text(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bytes):
            text = decode_best(value)
        else:
            text = str(value)
        text = text.strip()
        if text:
            return text
    return None


def split_recipients(value: Optional[str]) -> List[str]:
    if not value:
        return []
    separator = ";" if ";" in value else ","
    return [item.strip() for item in value.split(separator) if item.strip()]


def parse_references(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.replace("\n", " ").split() if part.strip()]


def html_to_text(value: str) -> str:
    text = value.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    parts: List[str] = []
    in_tag = False
    for char in text:
        if char == "<":
            in_tag = True
            continue
        if char == ">":
            in_tag = False
            continue
        if not in_tag:
            parts.append(char)
    return "".join(parts)


def dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
