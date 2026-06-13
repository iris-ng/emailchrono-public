import re
from typing import Iterable, List, Optional, Tuple

from ..parsers.base import EmailParseResult
from ..parsers.eml import parse_date
from .email_text import (
    CJK_HEADER_START_RE,
    ON_WROTE_RE,
    OUTLOOK_DELIMITER_RE,
    OUTLOOK_HEADER_DATE_RE,
    OUTLOOK_HEADER_START_RE,
    OUTLOOK_HEADER_SUBJECT_RE,
    OUTLOOK_HEADER_TO_RE,
    QuotedBlock,
    find_next_quoted_boundary,
    is_cjk_header_continuation,
    match_cjk_header,
    parse_cjk_block,
    parse_header_line,
    parse_outlook_block,
    split_header_list,
    strip_quote_prefixes,
)
from .text_norm import canonical_body, similarity_ratio


EMAIL_IN_ANGLE_RE = re.compile(r"<[^<>\s]+@[^<>\s]+>")

# Two body blocks counted as the same message when their text is at least this
# similar (difflib ratio). Ported from approach1/postprocess.py, which dropped
# adjacent rows with ratio >= 0.7 after sorting.
SIMILARITY_THRESHOLD = 0.7


def _normalize_for_similarity(value: str) -> str:
    # Shared with the duplicate scorer so ingest-time quoted-block dedup and the
    # candidate scorer agree on what "the same body" means.
    return canonical_body(value)


def bodies_similar(left_norm: str, right_norm: str) -> bool:
    """Near-identical check on two ALREADY-normalized bodies.

    Separated from normalization so a caller comparing one body against many
    can normalize each body once (with ``canonical_body``) instead of paying the
    NFKC+regex normalization cost on every pairwise call.
    """
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    return similarity_ratio(left_norm, right_norm, SIMILARITY_THRESHOLD) >= SIMILARITY_THRESHOLD


def _is_similar(a: str, b: str) -> bool:
    return bodies_similar(_normalize_for_similarity(a), _normalize_for_similarity(b))


def is_duplicate_of_any(body: str, existing_bodies: Iterable[str]) -> bool:
    """True when ``body`` is near-identical to any of ``existing_bodies``.

    ``body`` is normalized once; each existing body is normalized per call. For
    repeated checks against a fixed set, pre-normalize the set once and call
    ``bodies_similar`` directly (see ``reconcile_quoted_duplicates``).
    """
    target = _normalize_for_similarity(body)
    if not target:
        return False
    return any(bodies_similar(target, _normalize_for_similarity(other)) for other in existing_bodies)


def extract_quoted_blocks(
    parent: EmailParseResult, parent_email_id: int, default_tz: str = "UTC"
) -> List[EmailParseResult]:
    blocks = find_quoted_blocks(parent.body_text, default_tz)
    # Drop any quoted block that is really just a near-duplicate of the visible top
    # message (common when a client re-quotes the body it is replying to).
    blocks = [block for block in blocks if not _is_similar(block.body_text, parent.body_text)]
    results: List[EmailParseResult] = []
    for index, block in enumerate(blocks, start=1):
        parsed = EmailParseResult(
            source_file=parent.source_file,
            source_file_display=f"{parent.source_file_display} quoted #{index}",
            message_id=None,
            in_reply_to=parent.message_id,
            references=dedupe_text([*parent.references, *[ref for ref in [parent.message_id] if ref]]),
            from_addr=block.from_addr,
            to=block.to,
            cc=block.cc,
            date_utc=block.date_utc,
            date_raw=block.date_raw,
            subject=block.subject or parent.subject,
            body_text=block.body_text,
            body_html_raw="",
            body_html_sanitized="",
            body_format="text",
            parse_confidence=block.confidence,
            flags=["quoted_parse_uncertain", f"boundary:{block.boundary_method}"],
            source_kind="quoted",
            parent_email_id=parent_email_id,
            source_import_mode=parent.source_import_mode,
            source_openable=parent.source_openable,
            source_size=parent.source_size,
            source_mtime=parent.source_mtime,
            source_sha256=parent.source_sha256,
            attachments=[],
            boundary_method=block.boundary_method,
            boundary_evidence=block.boundary_evidence or [],
            relation_confidence="low" if block.confidence == "low" else "med",
        )
        setattr(parsed, "source_start_offset", block.source_start_offset)
        setattr(parsed, "source_end_offset", block.source_end_offset)
        results.append(parsed)
    return results


def find_quoted_blocks(body_text: str, default_tz: str = "UTC") -> List[QuotedBlock]:
    if not body_text:
        return []
    candidates: List[Tuple[int, QuotedBlock]] = []
    candidates.extend(find_outlook_delimited_blocks(body_text, default_tz))
    candidates.extend(find_outlook_header_blocks(body_text, default_tz))
    candidates.extend(find_on_wrote_blocks(body_text, default_tz))
    candidates.extend(find_cjk_header_blocks(body_text, default_tz))
    candidates.sort(key=lambda item: item[0])
    return dedupe_blocks([block for _, block in candidates])


def find_outlook_delimited_blocks(body_text: str, default_tz: str = "UTC") -> List[Tuple[int, QuotedBlock]]:
    matches = list(OUTLOOK_DELIMITER_RE.finditer(body_text))
    blocks = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body_text)
        # Stop at the next "On ... wrote:" delimiter too, so a deeper quoted message
        # is not swallowed into this block's body.
        next_on_wrote = ON_WROTE_RE.search(body_text, start)
        if next_on_wrote and next_on_wrote.start() < end:
            end = next_on_wrote.start()
        block = parse_outlook_block(body_text[start:end], default_tz)
        if block:
            block.source_start_offset = match.start()
            block.source_end_offset = end
            blocks.append((match.start(), block))
    return blocks


def _preceded_by_outlook_delimiter(body_text: str, pos: int) -> bool:
    """True when the nearest non-empty line before ``pos`` is an Outlook delimiter."""
    preceding = [line.strip() for line in body_text[:pos].splitlines() if line.strip()]
    if not preceding:
        return False
    return bool(re.match(r"^-{2,}\s*Original Message\s*-{2,}$", preceding[-1], re.I))


def find_outlook_header_blocks(body_text: str, default_tz: str = "UTC") -> List[Tuple[int, QuotedBlock]]:
    blocks = []
    for match in OUTLOOK_HEADER_START_RE.finditer(body_text):
        # Skip headers that belong to an "-----Original Message-----" block; those are
        # already handled by find_outlook_delimited_blocks, and matching them here
        # would emit a duplicate record for the same quoted email.
        if _preceded_by_outlook_delimiter(body_text, match.start()):
            continue
        # Outlook quoted blocks usually present several headers together. Requiring
        # these nearby labels prevents ordinary prose from becoming a synthetic email.
        window = body_text[match.start() : match.start() + 800]
        if not OUTLOOK_HEADER_DATE_RE.search(window):
            continue
        if not OUTLOOK_HEADER_TO_RE.search(window):
            continue
        if not OUTLOOK_HEADER_SUBJECT_RE.search(window):
            continue
        end = find_next_quoted_boundary(body_text, match.end())
        block = parse_outlook_block(body_text[match.start() : end], default_tz)
        if block:
            block.source_start_offset = match.start()
            block.source_end_offset = end
            blocks.append((match.start(), block))
    return blocks


def find_on_wrote_blocks(body_text: str, default_tz: str = "UTC") -> List[Tuple[int, QuotedBlock]]:
    matches = list(ON_WROTE_RE.finditer(body_text))
    blocks = []
    for match in matches:
        start = match.end()
        end = find_next_quoted_boundary(body_text, start)
        body = strip_quote_prefixes(body_text[start:end].strip())
        if not body:
            continue
        date_raw, from_addr = parse_on_wrote_detail(match.group("detail"))
        date_utc, flags = parse_date(date_raw, default_tz)
        blocks.append(
            (
                match.start(),
                QuotedBlock(
                    from_addr=from_addr,
                    to=[],
                    cc=[],
                    date_raw=date_raw,
                    date_utc=date_utc,
                    subject="",
                    body_text=body,
                    source_start_offset=match.start(),
                    source_end_offset=end,
                    confidence="low" if flags else "med",
                    boundary_method="on_wrote",
                    boundary_evidence=["On ... wrote: reply marker"],
                ),
            )
        )
    return blocks


def parse_on_wrote_detail(detail: str) -> Tuple[Optional[str], str]:
    # Collapse any line wrapping inside the header to a single line first.
    cleaned = " ".join(detail.split()).rstrip(":").strip()

    # Gmail style: "On <date>[,| at] <time> <name> <email> wrote:". When an address
    # is present, the sender is the name immediately before it and the date is the
    # remainder; this is far more reliable than splitting on the last comma.
    match = EMAIL_IN_ANGLE_RE.search(cleaned)
    if match:
        before = cleaned[: match.start()].rstrip()
        email = cleaned[match.start() : match.end()]
        name = _trailing_name(before)
        from_addr = f"{name} {email}".strip()
        date_part = before[: len(before) - len(name)].strip().rstrip(",").strip()
        return (date_part or None), from_addr

    if "," not in cleaned:
        return (cleaned or None), ""
    date_part, from_part = cleaned.rsplit(",", 1)
    return date_part.strip() or None, from_part.strip()


def _trailing_name(before: str) -> str:
    """Sender display name = trailing word(s) of ``before`` that aren't date/time."""
    name_words: List[str] = []
    for word in reversed(before.split()):
        if any(char.isdigit() for char in word) or word.upper() in {"AM", "PM", "AT"}:
            break
        name_words.insert(0, word)
        if len(name_words) >= 3:
            break
    return " ".join(name_words)


def dedupe_blocks(blocks: Iterable[QuotedBlock]) -> List[QuotedBlock]:
    seen = set()
    result: List[QuotedBlock] = []
    for block in blocks:
        key = (
            block.from_addr.lower(),
            (block.subject or "").lower(),
            block.body_text[:500].strip().lower(),
        )
        if key in seen:
            continue
        # Fuzzy guard: different delimiters (e.g. an "Original Message" header block
        # and an "On ... wrote:" block) can describe the same quoted message. Keep the
        # first one seen and drop near-duplicate bodies.
        if any(_is_similar(block.body_text, kept.body_text) for kept in result):
            continue
        seen.add(key)
        result.append(block)
    return result


def find_cjk_header_blocks(body_text: str, default_tz: str = "UTC") -> List[Tuple[int, QuotedBlock]]:
    blocks: List[Tuple[int, QuotedBlock]] = []
    starts = [
        match.start()
        for match in CJK_HEADER_START_RE.finditer(body_text)
        if not is_cjk_header_continuation(body_text, match.start())
    ]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(body_text)
        # Stop early if a non-CJK delimiter opens a different quoted block first.
        for other in (OUTLOOK_DELIMITER_RE.search(body_text, start + 1),
                      ON_WROTE_RE.search(body_text, start + 1)):
            if other and start < other.start() < end:
                end = other.start()
        block = parse_cjk_block(body_text[start:end], default_tz)
        if block:
            block.source_start_offset = start
            block.source_end_offset = end
            blocks.append((start, block))
    return blocks


def dedupe_text(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
