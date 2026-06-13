import hashlib
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .fingerprint import Fingerprint, body_containment, containment_from_hashes, minhash_jaccard
from .text_norm import (
    canonical_body,
    normalize_message_ref,
    normalize_subject,
    similarity_ratio,
)


BODY_EXACT_MIN_LENGTH = 40
BODY_SIMILAR_MIN_LENGTH = 80
BODY_SIMILAR_THRESHOLD = 0.92
BODY_STRONG_SIMILAR_THRESHOLD = 0.94
# MinHash-estimated body overlap. STRONG stands on its own; the lower threshold
# only counts with corroborating context (same subject / sender / close date).
BODY_JACCARD_THRESHOLD = 0.72
BODY_JACCARD_STRONG_THRESHOLD = 0.85
# One body embedded in a much larger one (quote/forward): fraction of the
# smaller body found in the larger. A structural hint, not a pure-duplicate
# claim, so it scores below confirmed content matches and stays human-reviewed.
BODY_CONTAINMENT_THRESHOLD = 0.90
BODY_CONTAINMENT_SCORE = 0.93
DATE_CLOSE_SECONDS = 10 * 60

# Reason codes that mean two rows are an exact (not merely similar) match.
EXACT_REASON_CODES = {"same_source_sha256", "same_message_id", "same_body_hash"}

# Lower rank = better candidate to keep as the canonical copy.
SOURCE_KIND_CANONICAL_RANK = {"standalone": 0, "attached": 1, "snipped": 2, "quoted": 3}


def duplicate_score(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    left_fp: Optional[Fingerprint] = None,
    right_fp: Optional[Fingerprint] = None,
) -> Optional[Tuple[float, List[Dict[str, Any]]]]:
    reasons: List[Dict[str, Any]] = []
    score = 0.0

    left_sha = (left.get("source_sha256") or "").strip()
    right_sha = (right.get("source_sha256") or "").strip()
    if left_sha and left_sha == right_sha:
        reasons.append({"code": "same_source_sha256", "label": "Same source file hash"})
        score = max(score, 1.0)

    left_message_id = normalize_message_ref(left.get("message_id"))
    right_message_id = normalize_message_ref(right.get("message_id"))
    if left_message_id and left_message_id == right_message_id:
        reasons.append({"code": "same_message_id", "label": "Same Message-ID"})
        score = max(score, 0.99)

    # Reuse the fingerprint's precomputed normalized body / signature / shingle
    # hashes (recompute builds them once per email); only normalize on the fly
    # when no fingerprint was supplied.
    left_signature = left_fp.signature if left_fp else None
    right_signature = right_fp.signature if right_fp else None
    left_body = left_fp.normalized if left_fp is not None else canonical_body(left.get("body_text"))
    right_body = right_fp.normalized if right_fp is not None else canonical_body(right.get("body_text"))
    if left_body and right_body:
        min_len = min(len(left_body), len(right_body))
        if body_hash(left_body) == body_hash(right_body) and min_len >= BODY_EXACT_MIN_LENGTH:
            reasons.append({"code": "same_body_hash", "label": "Same normalized body"})
            score = max(score, 0.97)
        else:
            context = duplicate_context(left, right)
            body_matched = False

            # MinHash-estimated Jaccard overlap of the body shingles. Unlike
            # SequenceMatcher.ratio() this is order- and length-tolerant, so it
            # still fires when paragraphs are reordered or one body carries an
            # added footer -- cases the exact body/prefix keys and ratio() miss.
            jaccard = minhash_jaccard(left_signature, right_signature)
            if jaccard >= BODY_JACCARD_STRONG_THRESHOLD or (
                jaccard >= BODY_JACCARD_THRESHOLD and context
            ):
                reasons.append(
                    {
                        "code": "body_shingle_jaccard",
                        "label": f"Body {round(jaccard * 100)}% overlap",
                        "value": round(jaccard, 4),
                    }
                )
                reasons.extend(context)
                if jaccard >= BODY_JACCARD_STRONG_THRESHOLD:
                    # Scale within (exact-hash 0.97 .. cutoff 0.92): 0.85 -> 0.94.
                    score = max(score, min(0.96, 0.94 + (jaccard - BODY_JACCARD_STRONG_THRESHOLD) * 0.13))
                else:
                    score = max(score, BODY_SIMILAR_THRESHOLD)
                body_matched = True

            # Character-level check for comparable-length bodies. SequenceMatcher
            # is O(n*m) -- too costly to run on every LSH-grouped candidate. The
            # MinHash Jaccard above already covers any body long enough to have a
            # signature, so only fall back to SequenceMatcher when a body is too
            # short to fingerprint.
            if (
                not body_matched
                and not (left_signature and right_signature)
                and min_len >= BODY_SIMILAR_MIN_LENGTH
            ):
                similarity = body_similarity(left_body, right_body)
                if similarity >= BODY_STRONG_SIMILAR_THRESHOLD or (
                    similarity >= BODY_SIMILAR_THRESHOLD and context
                ):
                    reasons.append(
                        {
                            "code": "body_similarity",
                            "label": f"Body {round(similarity * 100)}% similar",
                            "value": round(similarity, 4),
                        }
                    )
                    reasons.extend(context)
                    score = max(score, min(0.96, similarity + min(0.03, len(context) * 0.01)))
                    body_matched = True

            # Containment fallback: one body embedded in a much larger one (a
            # forward, or a reply quoting the original). Both signals above miss
            # it -- Jaccard because the union is large, ratio() because the
            # lengths differ. Cheap now: a set intersection over the fingerprints'
            # precomputed shingle hashes, so no size-disparity gate is needed.
            if not body_matched and min_len >= BODY_SIMILAR_MIN_LENGTH:
                if left_fp is not None and right_fp is not None:
                    containment = containment_from_hashes(left_fp.hashes, right_fp.hashes)
                else:
                    containment = body_containment(left_body, right_body)
                if containment >= BODY_CONTAINMENT_THRESHOLD:
                    reasons.append(
                        {
                            "code": "body_containment",
                            "label": f"Body {round(containment * 100)}% contained (likely quote/forward)",
                            "value": round(containment, 4),
                        }
                    )
                    reasons.extend(context)
                    score = max(score, BODY_CONTAINMENT_SCORE)

    if score < BODY_SIMILAR_THRESHOLD:
        return None
    return round(score, 4), dedupe_reasons(reasons)


def reasons_are_exact(reasons: Iterable[Mapping[str, Any]]) -> bool:
    """True if any reason marks the pair as an exact (non-fuzzy) duplicate."""
    return any(reason.get("code") in EXACT_REASON_CODES for reason in reasons)


def _canonical_sort_key(email: Mapping[str, Any]) -> Tuple[int, int, int, str, int]:
    kind_rank = SOURCE_KIND_CANONICAL_RANK.get(email.get("source_kind") or "", 4)
    body_len = len(canonical_body(email.get("body_text")))
    date = (email.get("date_utc") or "").strip()
    # Prefer: better source kind, longer body, has a date, earlier date, lower id.
    return (kind_rank, -body_len, 0 if date else 1, date or "~", int(email.get("id") or 0))


def suggest_canonical(emails: Iterable[Mapping[str, Any]]) -> Optional[int]:
    """Pick the email best kept as canonical (the rest become duplicates)."""
    candidates = [email for email in emails if email and email.get("id") is not None]
    if not candidates:
        return None
    return int(min(candidates, key=_canonical_sort_key)["id"])


def body_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def body_similarity(left: str, right: str) -> float:
    return similarity_ratio(left, right, BODY_SIMILAR_THRESHOLD)


def duplicate_context(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    reasons: List[Dict[str, Any]] = []
    if normalize_subject(left.get("subject")) == normalize_subject(right.get("subject")):
        reasons.append({"code": "same_subject", "label": "Same normalized subject"})
    if normalize_contact(left.get("from_addr")) == normalize_contact(right.get("from_addr")):
        reasons.append({"code": "same_sender", "label": "Same sender"})
    if dates_are_close(left.get("date_utc"), right.get("date_utc")):
        reasons.append({"code": "close_date", "label": "Dates within 10 minutes"})
    return reasons


def normalize_contact(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def dates_are_close(left: Optional[str], right: Optional[str]) -> bool:
    if not left or not right:
        return False
    try:
        left_dt = datetime.fromisoformat(left)
        right_dt = datetime.fromisoformat(right)
    except ValueError:
        return False
    return abs((left_dt - right_dt).total_seconds()) <= DATE_CLOSE_SECONDS


def dedupe_reasons(reasons: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for reason in reasons:
        code = reason.get("code")
        if code in seen:
            continue
        seen.add(code)
        result.append(reason)
    return result
