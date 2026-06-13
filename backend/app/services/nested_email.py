"""Turn an email-bearing attachment into a parsed EmailParseResult.

An attachment is "email-bearing" when it is a message/rfc822 part, an .eml/.msg
file attachment, or an embedded .msg (the latter is parsed eagerly upstream and
arrives via AttachmentParseResult.embedded_parsed). This module is the single
dispatch point the ingest pipeline calls for every att.is_email attachment.
"""

from typing import Optional

from ..parsers.base import AttachmentParseResult, EmailParseResult
from ..parsers.eml import parse_eml_bytes
from ..parsers.msg import parse_msg_bytes


def parse_nested_email(
    att: AttachmentParseResult, display: str, default_tz: str = "UTC"
) -> Optional[EmailParseResult]:
    # Embedded .msg messages were parsed while the parent file was still open
    # (extract_msg invalidates child objects after close), so reuse that result.
    if att.embedded_parsed is not None:
        result: EmailParseResult = att.embedded_parsed  # type: ignore[assignment]
        result.source_file = display
        result.source_file_display = display
        return result

    if not att.content:
        return None

    name = (att.filename or "").strip().lower()
    mime = (att.mime or "").strip().lower()
    try:
        if mime == "message/rfc822" or name.endswith(".eml"):
            return parse_eml_bytes(att.content, display, default_tz)
        if name.endswith(".msg") or mime in {"application/vnd.ms-outlook", "application/x-msg"}:
            return parse_msg_bytes(att.content, display, default_tz)
    except Exception:
        return None
    return None
