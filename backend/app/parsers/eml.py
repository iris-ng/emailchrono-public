from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import getaddresses
from typing import Iterable, List, Optional, Tuple

from charset_normalizer import from_bytes

from .base import AttachmentParseResult, EmailParseResult
from ..services.dates import to_utc
from ..services.sanitize import sanitize_html


def parse_eml_bytes(content: bytes, source_file_display: str, default_tz: str = "UTC") -> EmailParseResult:
    message = BytesParser(policy=policy.default).parsebytes(content)
    flags: List[str] = []

    date_raw = message.get("Date")
    date_utc, date_flags = parse_date(date_raw, default_tz)
    flags.extend(date_flags)

    message_id = clean_header_value(message.get("Message-ID"))
    if not message_id:
        flags.append("missing_message_id")

    body_text, body_html, attachments = extract_parts(message)
    sanitized_html = sanitize_html(body_html)
    if body_html and sanitized_html != body_html:
        flags.append("html_sanitized")

    body_format = "html" if body_html else "text"
    parse_confidence = "low" if "missing_date" in flags or "malformed_date" in flags else "high"
    if "missing_message_id" in flags and parse_confidence == "high":
        parse_confidence = "med"

    return EmailParseResult(
        source_file=source_file_display,
        source_file_display=source_file_display,
        message_id=message_id,
        in_reply_to=clean_header_value(message.get("In-Reply-To")),
        references=parse_references(message.get("References")),
        from_addr=format_addresses(message.get_all("From", [])),
        to=format_address_list(message.get_all("To", [])),
        cc=format_address_list(message.get_all("Cc", [])),
        date_utc=date_utc,
        date_raw=date_raw,
        subject=decode_mime_header(message.get("Subject")) or "(no subject)",
        body_text=body_text.strip(),
        body_html_raw=body_html,
        body_html_sanitized=sanitized_html,
        body_format=body_format,
        parse_confidence=parse_confidence,
        flags=dedupe(flags),
        attachments=attachments,
        # Outlook/Exchange-origin .eml carries these as transport headers; plain
        # SMTP mail does not. Thread-Index is base64 (kept raw, never MIME-decoded);
        # Thread-Topic may be RFC 2047 encoded, so decode it like any header.
        conversation_index=(message.get("Thread-Index") or "").strip() or None,
        conversation_topic=clean_header_value(message.get("Thread-Topic")),
    )


def parse_date(value: Optional[str], default_tz: str = "UTC") -> Tuple[Optional[str], List[str]]:
    if not value:
        return None, ["missing_date"]
    iso = to_utc(value, default_tz)
    if iso is None:
        return None, ["malformed_date"]
    return iso, []


def decode_mime_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


def clean_header_value(value: Optional[str]) -> Optional[str]:
    decoded = decode_mime_header(value)
    return decoded or None


def parse_references(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.replace("\n", " ").split() if part.strip()]


def format_addresses(values: Iterable[str]) -> str:
    addresses = getaddresses(values)
    if not addresses:
        return ""
    name, addr = addresses[0]
    return format_single_address(name, addr)


def format_address_list(values: Iterable[str]) -> List[str]:
    return [format_single_address(name, addr) for name, addr in getaddresses(values)]


def format_single_address(name: str, addr: str) -> str:
    decoded_name = decode_mime_header(name)
    if decoded_name and addr:
        return f"{decoded_name} <{addr}>"
    return addr or decoded_name


def extract_parts(message: Message) -> Tuple[str, str, List[AttachmentParseResult]]:
    text_parts: List[str] = []
    html_parts: List[str] = []
    attachments: List[AttachmentParseResult] = []
    _walk_parts(message, text_parts, html_parts, attachments)
    return "\n\n".join(filter(None, text_parts)), "\n\n".join(filter(None, html_parts)), attachments


def _walk_parts(
    part: Message,
    text_parts: List[str],
    html_parts: List[str],
    attachments: List[AttachmentParseResult],
) -> None:
    content_type = part.get_content_type()

    # An attached message (message/rfc822) is multipart-ish, so the old walk()
    # loop descended into it and merged its text/html into THIS message's body.
    # Capture it as a self-contained email attachment and do not descend, so the
    # parent body stays clean and the nested message becomes its own timeline row.
    if content_type == "message/rfc822":
        nested = part.get_payload(0) if part.is_multipart() else None
        nested_bytes = nested.as_bytes() if nested is not None else (part.get_payload(decode=True) or b"")
        filename = part.get_filename()
        attachments.append(
            AttachmentParseResult(
                filename=decode_mime_header(filename) or nested_email_filename(nested),
                mime="message/rfc822",
                content=nested_bytes,
                content_id=strip_content_id(part.get("Content-ID")),
                is_inline=False,
                is_email=True,
            )
        )
        return

    if part.is_multipart():
        for sub in part.get_payload():
            if isinstance(sub, Message):
                _walk_parts(sub, text_parts, html_parts, attachments)
        return

    content_disposition = part.get_content_disposition()
    filename = part.get_filename()
    content_id = part.get("Content-ID")
    is_attachment = content_disposition == "attachment" or bool(filename)
    is_inline_asset = content_disposition == "inline" and content_id and not content_type.startswith("text/")

    if is_attachment or is_inline_asset:
        payload = part.get_payload(decode=True) or b""
        decoded_name = decode_mime_header(filename) or "attachment"
        attachments.append(
            AttachmentParseResult(
                filename=decoded_name,
                mime=content_type,
                content=payload,
                content_id=strip_content_id(content_id),
                is_inline=bool(is_inline_asset),
                # A file attachment that is itself an email (e.g. a forwarded
                # "FW message.eml") is also surfaced as its own timeline row.
                is_email=is_email_filename(decoded_name),
            )
        )
        return

    if content_type == "text/plain":
        text_parts.append(get_text_content(part))
    elif content_type == "text/html":
        html_parts.append(get_text_content(part))


def is_email_filename(filename: Optional[str]) -> bool:
    if not filename:
        return False
    return filename.strip().lower().endswith((".eml", ".msg"))


def nested_email_filename(nested: Optional[Message]) -> str:
    if nested is not None:
        subject = decode_mime_header(nested.get("Subject"))
        if subject:
            cleaned = "".join(ch for ch in subject if ch.isalnum() or ch in {" ", "_", "-"}).strip()
            if cleaned:
                return f"{cleaned[:80]}.eml"
    return "attached-message.eml"


def get_text_content(part: Message) -> str:
    if isinstance(part, EmailMessage):
        try:
            return part.get_content()
        except Exception:
            pass
    payload = part.get_payload(decode=True)
    if payload is None:
        value = part.get_payload()
        return value if isinstance(value, str) else ""
    charset = part.get_content_charset()
    if charset:
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            pass
    # No (or unknown) declared charset: detect rather than assume UTF-8, so CJK
    # bodies sent without a charset header don't decode to replacement chars.
    try:
        best = from_bytes(payload).best()
    except Exception:
        best = None
    if best is not None:
        return str(best)
    return payload.decode("utf-8", errors="replace")


def strip_content_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().strip("<>")


def dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
