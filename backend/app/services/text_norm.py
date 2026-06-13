"""Shared, dependency-free text/row helpers.

Single home for normalization and row/JSON utilities that were previously
copy-pasted across db.py, email_serialize.py, duplicates.py, audit.py and
tags.py. This module imports nothing from the app so every layer can use it
without creating an import cycle.
"""

import base64
import json
import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, Optional


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def normalize_message_ref(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = str(value).strip().strip("<>").strip().lower()
    return cleaned or None


# Reply/forward prefixes stripped so a thread collapses onto one subject key.
# ASCII plus the CJK forms Outlook/Foxmail emit: 回复/答复 (reply), 转发 (forward),
# and the traditional 回覆/答覆/轉發. Each requires a trailing colon -- ASCII ":" or
# the full-width "：" (U+FF1A), folded to ":" before matching -- so prose that
# merely starts with 回复 ("回复客户的问题") is left intact, mirroring the ASCII rule.
_SUBJECT_PREFIXES = (
    "re:",
    "fw:",
    "fwd:",
    "回复:",
    "回覆:",
    "答复:",
    "答覆:",
    "转发:",
    "轉發:",
)


def normalize_subject(value: Optional[str]) -> str:
    subject = (value or "").strip().replace("：", ":").lower()
    changed = True
    while changed:
        changed = False
        for prefix in _SUBJECT_PREFIXES:
            if subject.startswith(prefix):
                subject = subject[len(prefix) :].strip()
                changed = True
    return " ".join(subject.split()) or "no-subject"


def conversation_index_root(value: Optional[str]) -> Optional[str]:
    """Conversation root key from an Outlook Conversation-Index / Thread-Index.

    The value is base64 binary: a 22-byte header (reserved byte + 5-byte FILETIME
    + 16-byte GUID) shared by every message in a conversation, then a 5-byte block
    appended per reply. The header identifies the conversation independently of
    RFC Message-ID/References, so it threads Outlook ``.msg`` mail that carries no
    References chain. Returns the header as hex, or None when absent/malformed.
    """
    if not value:
        return None
    try:
        raw = base64.b64decode(str(value).strip())
    except Exception:
        return None
    if len(raw) < 22:
        return None
    return raw[:22].hex()


def fallback_thread_key(row: "sqlite3.Row") -> str:
    # Prefer the stable Outlook conversation topic over the raw subject when the
    # row carries one: it is already prefix-stripped and does not drift as the
    # subject line is edited down a thread.
    topic = None
    try:
        topic = row["conversation_topic"]
    except (IndexError, KeyError):
        topic = None
    return f"subj:{normalize_subject(topic or row['subject'])}"


# Characters with no textual meaning that mail clients sprinkle into bodies:
# zero-width space/non-joiner/joiner, word joiner, BOM (zero-width no-break
# space). Dropped before hashing so they can't defeat an identical match.
_ZERO_WIDTH_CHARS = dict.fromkeys(
    (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF), None
)

# Fold the typographic variants different clients emit for the same character
# down to a single ASCII form. NFKC does not unify curly quotes with straight
# ones, so do it explicitly. Keep these in sync with boilerplate._char_pattern.
_QUOTE_DASH_MAP = str.maketrans(
    {
        "‘": "'", "’": "'", "′": "'", "`": "'",
        "“": '"', "”": '"', "″": '"',
        "–": "-", "—": "-", "−": "-",
    }
)

# RFC 3676 signature delimiter: a line that is exactly "--" (optionally with a
# trailing space). Everything after it is the sender's signature, not message
# content. Exactly two dashes so we don't trip on "---"-style separators.
_SIGNATURE_DELIM_RE = re.compile(r"(?m)^--[ \t]*$")

# Auto-appended client footers that add noise without changing the message.
_MOBILE_FOOTER_RE = re.compile(
    r"(?im)^[ \t>]*(?:sent from my\b|get outlook for\b|sent from mail for windows\b).*$"
)


def _strip_signature(text: str) -> str:
    """Drop the signature block and common auto-footers (line structure intact)."""
    match = _SIGNATURE_DELIM_RE.search(text)
    if match:
        text = text[: match.start()]
    return _MOBILE_FOOTER_RE.sub("", text)


def similarity_ratio(left: str, right: str, min_ratio: float) -> float:
    """SequenceMatcher ratio of two strings, short-circuiting to 0.0 via the
    cheap real_quick_ratio / quick_ratio upper bounds when they already fall
    below ``min_ratio`` -- avoiding the full O(n*m) compare. Shared by the
    duplicate scorer and ingest-time quoted-block dedup so they agree.
    """
    matcher = SequenceMatcher(None, left, right)
    if matcher.real_quick_ratio() < min_ratio:
        return 0.0
    if matcher.quick_ratio() < min_ratio:
        return 0.0
    return matcher.ratio()


def canonical_body(value: Optional[str]) -> str:
    """Normalize a body for duplicate hashing / similarity.

    Beyond lowercasing and collapsing whitespace this folds Unicode (NFKC),
    maps smart quotes and dashes to ASCII, drops zero-width characters, and
    trims the signature block / common mobile footers — so trivial,
    client-introduced differences don't defeat exact-body or prefix matching.
    Operates on the boilerplate-stripped ``body_text``; quoted-line removal is
    intentionally left to the parser / future persisted ``body_norm``.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = text.translate(_ZERO_WIDTH_CHARS).translate(_QUOTE_DASH_MAP)
    text = _strip_signature(text)
    return " ".join(text.lower().split())
