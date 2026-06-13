"""Parse an email-like item printed/exported to PDF into an EmailParseResult.

Scanned / image-only PDFs (no extractable text) raise EmptyDocumentError -- no
OCR is attempted. PDFs whose text does not open with an email header cluster
raise NotAnEmailError (handled by ingest as a skipped, non-fatal file). A corrupt
or password-protected PDF that pdfplumber cannot open propagates the underlying
pdfminer exception; ingest catches it and records a failed file.
"""

import re
from collections import Counter
from io import BytesIO
from typing import List

import pdfplumber

from ..config import MAX_PDF_PAGES
from .base import EmailParseResult, EmptyDocumentError
from .base import DocumentIngestError
from ..services.email_text import build_printed_email_result


# A line that is just a page marker: "Page 3", "Page 3 of 12", "- 3 -", "3".
_PAGE_NUMBER_RE = re.compile(r"^\s*(?:page\s+)?[-–]?\s*\d+\s*(?:of\s+\d+)?\s*[-–]?\s*$", re.I)
# A page marker appearing inline within a footer line: "Acme Corp - Page 2 of 2".
# Used only to normalize per-page numbers so a footer template counts as
# repeating across pages; the page number varies but the template does not.
_PAGE_NUMBER_INLINE_RE = re.compile(r"page\s+\d+(?:\s+of\s+\d+)?", re.I)
# A word split across a line break by hyphenation: "ship-\nment" -> "shipment".
_LINE_WRAP_HYPHEN_RE = re.compile(r"([A-Za-zÀ-ɏ])-\n([a-zÀ-ɏ])")
# U+00AD SOFT HYPHEN (a literal, invisible char here; clients sprinkle it into
# justified text and it must be removed before body hashing).
_SOFT_HYPHEN = "­"


def _normalize_edge(line: str) -> str:
    """Normalize a top/bottom line for cross-page repeat detection.

    Collapses the varying page number -- whether the whole line is just a page
    number ("Page 3 of 12") or it is embedded in a footer template ("Acme Corp -
    Page 3 of 12") -- to a fixed token so the template counts as repeating.
    """
    stripped = line.strip()
    if _PAGE_NUMBER_RE.match(stripped):
        return "#"
    return _PAGE_NUMBER_INLINE_RE.sub("#", stripped)


def _drop_running_headers_footers(pages: List[str]) -> List[List[str]]:
    """Drop lines that repeat as the first/last line across most pages.

    Running headers/footers (e.g. "CONFIDENTIAL", "Acme Corp - Page N of M")
    appear on (almost) every page and would otherwise pollute the body hash.
    Only the top and bottom lines of each page are eligible so genuine repeated
    body text is never removed. Requires 2+ pages to trigger.
    """
    page_lines = [[ln for ln in p.replace("\r\n", "\n").split("\n")] for p in pages]
    if len(page_lines) < 2:
        return page_lines

    edge_counts: Counter = Counter()
    for lines in page_lines:
        nonblank = [ln for ln in lines if ln.strip()]
        if not nonblank:
            continue
        # Page-number lines vary per page; normalize them so the footer template
        # ("Acme Corp - Page N of M") still counts as repeating.
        edge_counts[_normalize_edge(nonblank[0])] += 1
        edge_counts[_normalize_edge(nonblank[-1])] += 1

    threshold = max(2, (len(page_lines) + 1) // 2)
    repeating = {key for key, count in edge_counts.items() if count >= threshold}

    cleaned: List[List[str]] = []
    for lines in page_lines:
        # Only the first/last NON-BLANK line of each page is eligible for removal,
        # matching the contract above. Dropping any interior line whose text merely
        # normalizes to a repeating key would risk deleting genuine body content
        # (e.g. a sentence mentioning "page 3") -- unacceptable for discovery work.
        nonblank_idx = [i for i, ln in enumerate(lines) if ln.strip()]
        edges = {nonblank_idx[0], nonblank_idx[-1]} if nonblank_idx else set()
        kept = [
            ln
            for i, ln in enumerate(lines)
            if not (i in edges and _normalize_edge(ln) in repeating)
        ]
        cleaned.append(kept)
    return cleaned


def clean_pdf_pages(pages: List[str]) -> str:
    """Turn per-page extracted text into one clean body string.

    Removes running headers/footers and standalone page numbers, strips soft
    hyphens, and rejoins words broken across line wraps. Header lines stay on
    their own lines (the header parser is line-sensitive); paragraph de-wrapping
    is intentionally NOT done because canonical_body collapses all whitespace for
    hashing anyway, and de-wrapping risks merging header lines.
    """
    page_lines = _drop_running_headers_footers(pages)
    out_lines: List[str] = []
    for lines in page_lines:
        for ln in lines:
            if _PAGE_NUMBER_RE.match(ln):
                continue
            out_lines.append(ln)
    text = "\n".join(out_lines)
    text = text.replace(_SOFT_HYPHEN, "")
    text = _LINE_WRAP_HYPHEN_RE.sub(r"\1\2", text)
    return text.strip()


def _extract_pages(content: bytes) -> List[str]:
    pages: List[str] = []
    with pdfplumber.open(BytesIO(content)) as pdf:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise DocumentIngestError(
                f"PDF exceeds {MAX_PDF_PAGES} page ingest limit."
            )
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages


def parse_pdf_bytes(
    content: bytes, source_file_display: str, default_tz: str = "UTC"
) -> EmailParseResult:
    pages = _extract_pages(content)
    if not any(p.strip() for p in pages):
        raise EmptyDocumentError(
            "No extractable text in PDF (scanned/image-only?); OCR is not performed."
        )
    text = clean_pdf_pages(pages)
    return build_printed_email_result(
        text, source_file_display, default_tz, source_format="pdf"
    )
