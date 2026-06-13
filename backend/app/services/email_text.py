"""Shared text->email-header parsing primitives.

These leaf-level helpers were factored out of services/quotes.py so both the
quoted-block extractor and the printed-document parsers (parsers/pdf.py,
parsers/docx.py) reuse one implementation of "given a chunk of text that looks
like an email header block, parse it into sender/recipients/date/subject/body".

quotes.py keeps the higher-level orchestration (find_quoted_blocks and the
per-delimiter finders) and imports the primitives below. The printed-document
path additionally uses looks_like_printed_email() / build_printed_email_result()
defined at the bottom of this module.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..parsers.base import EmailParseResult, NotAnEmailError
from ..parsers.eml import parse_date


OUTLOOK_DELIMITER_RE = re.compile(r"(?im)^-{2,}\s*Original Message\s*-{2,}\s*$")
# "On <date> <sender> wrote:" reply marker (tolerant of indentation/">" prefixes
# and of the header wrapping across lines before "wrote:").
ON_WROTE_RE = re.compile(r"(?ims)^[ \t>]*On\s+(?P<detail>.{1,200}?)\s+wrote:[ \t\r]*$")
OUTLOOK_HEADER_START_RE = re.compile(r"(?im)^[ \t>]*\*?\s*From\s*\*?\s*:\s*\*?\s*.+\r?$")
OUTLOOK_HEADER_DATE_RE = re.compile(r"(?im)^[ \t>]*\*?\s*(Sent|Date)\s*\*?\s*:\s*\*?\s*.+\r?$")
OUTLOOK_HEADER_TO_RE = re.compile(r"(?im)^[ \t>]*\*?\s*To\s*\*?\s*:\s*\*?\s*.+\r?$")
OUTLOOK_HEADER_SUBJECT_RE = re.compile(r"(?im)^[ \t>]*\*?\s*Subject\s*\*?\s*:\s*\*?\s*.+\r?$")

# CJK (Chinese) reply markers. Header labels can contain full-width spaces, e.g.
# the full-width colon is U+FF1A. Defined with \u escapes to keep the source
# ASCII-safe regardless of editor/terminal encoding.
CJK_HEADER_START_RE = re.compile(
    r"(?im)^[\s>\t]*\*?\s*(?:"
    r"发\s*件\s*人|"
    r"寄\s*件\s*(?:人|者)|"
    r"发\s*送\s*(?:时\s*间|日\s*期)|"
    r"日\s*期|"
    r"Date"
    r")\s*\*?\s*[:：]\s*.*$"
)
CJK_WROTE_RE = re.compile(r"(?m)^.*写道[:：]?\s*$")
CJK_HEADER_LABELS = {
    "from": ("发件人", "寄件人", "寄件者", "from"),
    "sent": (
        "发送时间",
        "发送日期",
        "时间",
        "日期",
        "sent",
        "date",
    ),
    "to": ("收件人", "收件者", "to"),
    "cc": ("抄送人", "抄送", "cc"),
    "subject": ("主题", "主旨", "subject"),
}


@dataclass
class QuotedBlock:
    from_addr: str
    to: List[str]
    cc: List[str]
    date_raw: Optional[str]
    date_utc: Optional[str]
    subject: str
    body_text: str
    source_start_offset: Optional[int] = None
    source_end_offset: Optional[int] = None
    confidence: str = "low"
    boundary_method: str = "text_regex"
    boundary_evidence: List[str] = None


def parse_header_line(line: str) -> Optional[Tuple[str, str]]:
    stripped = re.sub(r"^(?:\s*>\s?)+", "", line).strip()
    match = re.match(
        r"^\*?\s*(From|Sent|Date|To|Cc|Subject)\s*\*?\s*:\s*\*?\s*(.*)$",
        stripped,
        re.I,
    )
    if not match:
        return None
    return match.group(1).lower(), match.group(2).strip()


def split_header_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    separator = ";" if ";" in value else ","
    return [item.strip() for item in value.split(separator) if item.strip()]


def strip_quote_prefixes(value: str) -> str:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    stripped = []
    for line in lines:
        stripped.append(re.sub(r"^\s*>\s?", "", line).rstrip())
    return "\n".join(stripped).strip()


def parse_outlook_block(value: str, default_tz: str = "UTC") -> Optional[QuotedBlock]:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    headers = {}
    body_start = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if headers:
                body_start = index + 1
                break
            continue
        header = parse_header_line(stripped)
        if not header:
            if headers:
                body_start = index
                break
            continue
        key, value = header
        headers[key] = value
    else:
        body_start = len(lines)

    body = "\n".join(lines[body_start:]).strip()
    if not headers or not body:
        return None

    date_raw = headers.get("sent") or headers.get("date")
    date_utc, flags = parse_date(date_raw, default_tz)
    return QuotedBlock(
        from_addr=headers.get("from", ""),
        to=split_header_list(headers.get("to")),
        cc=split_header_list(headers.get("cc")),
        date_raw=date_raw,
        date_utc=date_utc,
        subject=headers.get("subject", ""),
        body_text=strip_quote_prefixes(body),
        confidence="low" if flags else "med",
        boundary_method="outlook_header",
        boundary_evidence=["Outlook-style From/Sent/To/Subject block"],
    )


def match_cjk_header(line: str) -> Optional[Tuple[str, str]]:
    stripped = re.sub(r"^(?:\s*>\s?)+", "", line).strip().strip("*").strip()
    stripped = stripped.replace("　", " ")
    match = re.match(
        r"^\*?\s*(?P<label>[^:：]+?)\s*\*?\s*[:：]\s*\*?\s*(?P<value>.*)$",
        stripped,
    )
    if not match:
        return None
    label = re.sub(r"[\s*]+", "", match.group("label")).lower()
    for key, labels in CJK_HEADER_LABELS.items():
        if label in labels:
            return key, match.group("value").strip()
    return None


def is_cjk_header_continuation(body_text: str, start: int) -> bool:
    for line in reversed(body_text[:start].splitlines()):
        if not line.strip():
            return False
        if match_cjk_header(line):
            return True
        return False
    return False


def parse_cjk_block(value: str, default_tz: str = "UTC") -> Optional[QuotedBlock]:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    headers: dict = {}
    body_start = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if headers:
                body_start = index + 1
                break
            continue
        field = match_cjk_header(stripped)
        if not field:
            if headers:
                body_start = index
                break
            continue
        key, remainder = field
        headers[key] = remainder
    else:
        body_start = len(lines)

    body = "\n".join(lines[body_start:]).strip()
    if not headers or not body:
        return None
    if "sent" not in headers:
        return None

    date_raw = headers.get("sent")
    date_utc, flags = parse_date(date_raw, default_tz)
    return QuotedBlock(
        from_addr=headers.get("from", ""),
        to=split_header_list(headers.get("to")),
        cc=split_header_list(headers.get("cc")),
        date_raw=date_raw,
        date_utc=date_utc,
        subject=headers.get("subject", ""),
        body_text=strip_quote_prefixes(body),
        confidence="low",
        boundary_method="localized_header",
        boundary_evidence=["Localized header block"],
    )


def find_next_quoted_boundary(body_text: str, start: int) -> int:
    candidates = []
    for pattern in (
        OUTLOOK_DELIMITER_RE,
        OUTLOOK_HEADER_START_RE,
        ON_WROTE_RE,
        CJK_HEADER_START_RE,
    ):
        search_from = start
        match = pattern.search(body_text, search_from)
        while match and pattern is CJK_HEADER_START_RE and is_cjk_header_continuation(body_text, match.start()):
            search_from = match.end()
            match = pattern.search(body_text, search_from)
        if match:
            candidates.append(match.start())
    return min(candidates) if candidates else len(body_text)


# --- Printed-document classification gate + builder ---------------------------

# How many leading non-empty lines may precede / contain the header cluster
# before we give up looking (covers a short letterhead above the headers).
#
# This is a text-pattern gate, not semantic understanding: formal correspondence
# that opens with email-like labels (e.g. "From:" + "Date:" on a legal letter)
# can pass it. That false positive is an accepted tradeoff -- such a row lands
# with parse_confidence="low" and the "headers_recovered_from_text" flag, so the
# user sees it is suspect and can reject it. Tightening further would risk
# dropping genuine printed emails (the more costly error for discovery work).
_MAX_LEAD_LINES = 20

# Header fields that, alongside a ``From`` line, satisfy the classification gate.
# ``Cc`` is intentionally excluded: a From+Cc-only top is too weak a signal.
_GATE_SECONDARY_KINDS = ("sent", "to", "subject")


def _header_kind(line: str) -> Optional[str]:
    """Classify a single line as an email header field, or None.

    Recognizes both Western Outlook-style labels and the localized CJK labels.
    Note ``Date:`` and ``Sent:`` both classify as ``"sent"`` -- the gate treats
    them interchangeably and never needs to tell them apart.
    """
    if OUTLOOK_HEADER_START_RE.search(line):
        return "from"
    if OUTLOOK_HEADER_DATE_RE.search(line):
        return "sent"
    if OUTLOOK_HEADER_TO_RE.search(line):
        return "to"
    if OUTLOOK_HEADER_SUBJECT_RE.search(line):
        return "subject"
    cjk = match_cjk_header(line)
    if cjk:
        return cjk[0]
    return None


def _has_min_header_cluster(text: str) -> bool:
    """True when the document opens with an email header cluster.

    Requires a ``From`` line plus at least one of ``Sent``/``Date``/``To``/
    ``Subject`` within the first ``_MAX_LEAD_LINES`` non-empty lines. This is the
    email-only classification gate: contracts, invoices and scans lack it and are
    skipped rather than ingested as bogus emails.
    """
    kinds = set()
    seen = 0
    for raw in text.splitlines():
        if not raw.strip():
            continue
        seen += 1
        if seen > _MAX_LEAD_LINES:
            break
        kind = _header_kind(raw)
        if kind:
            kinds.add(kind)
    return "from" in kinds and any(k in kinds for k in _GATE_SECONDARY_KINDS)


def looks_like_printed_email(text: str, default_tz: str = "UTC") -> Optional[QuotedBlock]:
    """Parse the document's leading email header cluster, or return None.

    The returned block's ``body_text`` is everything after the leading header
    cluster -- including any downstream "From:/Sent:" quoted blocks -- so the
    caller can hand it to the standard quoted-block extractor to split the chain.

    Returns None when the gate fails, and also when the gate passes but neither
    parser can extract a usable block (e.g. a header cluster with no body after
    it, or a CJK cluster missing the required date field).
    """
    if not text or not _has_min_header_cluster(text):
        return None
    # parse_outlook_block / parse_cjk_block skip leading non-header lines (e.g. a
    # letterhead) until the header cluster begins, then take the remainder as body.
    block = parse_outlook_block(text, default_tz)
    if block is None:
        block = parse_cjk_block(text, default_tz)
    return block


def build_printed_email_result(
    text: str,
    source_file_display: str,
    default_tz: str = "UTC",
    *,
    source_format: str,
) -> EmailParseResult:
    """Build a standalone EmailParseResult from a printed/exported email document.

    Raises NotAnEmailError when the text does not open with an email header
    cluster. The whole recovered chain stays in ``body_text``; the standard
    parse_and_store flow then splits the quoted children, dedups and threads it.

    Printed emails carry no Message-ID/References/Conversation-Index, so they get
    parse_confidence="low", a "headers_recovered_from_text" flag, and thread by
    subject. source_sha256 (the file hash, set by the caller) still gives exact
    file-level dedup.
    """
    block = looks_like_printed_email(text, default_tz)
    if block is None:
        raise NotAnEmailError(
            f"No email header cluster found at the top of this {source_format} document."
        )
    subject = (block.subject or "").strip() or "(no subject)"
    return EmailParseResult(
        source_file=source_file_display,
        source_file_display=source_file_display,
        message_id=None,
        in_reply_to=None,
        references=[],
        from_addr=block.from_addr,
        to=block.to,
        cc=block.cc,
        date_utc=block.date_utc,
        date_raw=block.date_raw,
        subject=subject,
        body_text=block.body_text.strip(),
        body_html_raw="",
        body_html_sanitized="",
        body_format="text",
        parse_confidence="low",
        flags=[
            "headers_recovered_from_text",
            f"recovered_from:{source_format}",
        ],
        boundary_method="printed_document",
        boundary_evidence=[f"Email headers recovered from {source_format} text"],
        relation_confidence="low",
        conversation_index=None,
        conversation_topic=None,
    )
