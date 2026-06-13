import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .. import db
from ..services.audit import record_audit_event
from ..services.duplicates import (
    body_hash,
    duplicate_score,
    normalize_contact,
    reasons_are_exact,
    suggest_canonical,
)
from ..services.fingerprint import (
    Fingerprint,
    MIN_FINGERPRINT_LEN,
    lsh_band_keys,
    minhash_from_hashes,
    shingle_hashes,
)
from ..services.text_norm import (
    canonical_body,
    json_dumps,
    json_loads,
    normalize_message_ref,
    normalize_subject,
    row_to_dict,
)
from . import cases as case_repo
from . import emails as email_repo


def recompute_duplicate_candidates(case_id: int) -> int:
    with db.get_conn() as conn:
        return _recompute_duplicate_candidates(conn, case_id)


def _recompute_duplicate_candidates(conn: sqlite3.Connection, case_id: int) -> int:
    case = case_repo.get_case_by_id(conn, case_id)
    if not case:
        return 0
    rows = conn.execute(
        """
        SELECT *
        FROM emails
        WHERE case_id = ?
          AND deleted_at IS NULL
          AND superseded_at IS NULL
          AND source_kind IN ('standalone', 'attached', 'quoted', 'snipped')
        ORDER BY id
        """,
        (case_id,),
    ).fetchall()
    fingerprints = _ensure_fingerprints(conn, rows)
    candidate_pairs = duplicate_candidate_pairs(rows, fingerprints)
    generated_pairs = set()
    created_or_updated = 0
    now = db.utc_now()
    for left, right in candidate_pairs:
        left_fp = fingerprints.get(int(left["id"]))
        right_fp = fingerprints.get(int(right["id"]))
        scored = duplicate_score(
            row_to_dict(left),
            row_to_dict(right),
            left_fp=left_fp,
            right_fp=right_fp,
        )
        if not scored:
            continue
        score, reasons = scored
        email_a_id, email_b_id = sorted((left["id"], right["id"]))
        generated_pairs.add((email_a_id, email_b_id))
        existing = conn.execute(
            """
            SELECT *
            FROM email_duplicate_candidates
            WHERE case_id = ? AND email_a_id = ? AND email_b_id = ?
            """,
            (case_id, email_a_id, email_b_id),
        ).fetchone()
        if existing:
            if existing["status"] == "pending":
                conn.execute(
                    """
                    UPDATE email_duplicate_candidates
                    SET score = ?, reason_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (score, json_dumps(reasons), now, existing["id"]),
                )
                created_or_updated += 1
            continue
        conn.execute(
            """
            INSERT INTO email_duplicate_candidates
              (case_id, email_a_id, email_b_id, score, reason_json,
               status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                case_id,
                email_a_id,
                email_b_id,
                score,
                json_dumps(reasons),
                now,
                now,
            ),
        )
        created_or_updated += 1

    pending = conn.execute(
        """
        SELECT id, email_a_id, email_b_id
        FROM email_duplicate_candidates
        WHERE case_id = ? AND status = 'pending'
        """,
        (case_id,),
    ).fetchall()
    for row in pending:
        if (row["email_a_id"], row["email_b_id"]) not in generated_pairs:
            conn.execute("DELETE FROM email_duplicate_candidates WHERE id = ?", (row["id"],))
    return created_or_updated


def _ensure_fingerprints(
    conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]
) -> Dict[int, Fingerprint]:
    """Body fingerprints for ``rows``, persisting any missing or stale ones.

    The cheap canonical normalization runs every time and is compared against
    the stored ``body_norm``; only when it differs (new row, or the body was
    edited) is the expensive MinHash recomputed and written back. The shingle
    hashes are always derived (they feed per-pair containment) but are O(N), not
    O(N^2). This is a derived cache like the FTS index: no audit event, no
    ``cases.updated_at`` bump.
    """
    fingerprints: Dict[int, Fingerprint] = {}
    for row in rows:
        normalized = canonical_body(row["body_text"])
        hashes = shingle_hashes(normalized)
        if row["body_norm"] == normalized:
            signature = json_loads(row["body_minhash"], None)
        else:
            signature = minhash_from_hashes(hashes) if len(normalized) >= MIN_FINGERPRINT_LEN else None
            conn.execute(
                """
                UPDATE emails
                SET body_norm = ?, body_norm_len = ?, body_minhash = ?
                WHERE id = ?
                """,
                (
                    normalized,
                    len(normalized),
                    json_dumps(signature) if signature is not None else None,
                    row["id"],
                ),
            )
        fingerprints[int(row["id"])] = Fingerprint(normalized, signature, hashes)
    return fingerprints


# A single block this large is a low-precision subject/date bucket (e.g. a huge
# same-subject thread); scoring every pair in it is the only residual quadratic
# cost. Exact dups are still caught via the small sha/msg/body blocks.
MAX_BLOCK_SIZE = 400


def duplicate_candidate_pairs(
    rows: Sequence[sqlite3.Row],
    fingerprints: Optional[Dict[int, Fingerprint]] = None,
) -> List[Tuple[sqlite3.Row, sqlite3.Row]]:
    fingerprints = fingerprints or {}
    by_id = {row["id"]: row for row in rows}
    blocks: Dict[str, List[int]] = {}
    for row in rows:
        row_id = int(row["id"])
        for key in duplicate_block_keys(row, fingerprints.get(row_id)):
            blocks.setdefault(key, []).append(row_id)

    pair_ids = set()
    for ids in blocks.values():
        unique_ids = sorted(set(ids))
        if len(unique_ids) > MAX_BLOCK_SIZE:
            continue
        for index, left_id in enumerate(unique_ids):
            for right_id in unique_ids[index + 1 :]:
                pair_ids.add((left_id, right_id))
    return [(by_id[left_id], by_id[right_id]) for left_id, right_id in sorted(pair_ids)]


def duplicate_block_keys(
    row: sqlite3.Row, fingerprint: Optional[Fingerprint] = None
) -> List[str]:
    keys = []
    source_sha = (row["source_sha256"] or "").strip()
    if source_sha:
        keys.append(f"sha:{source_sha}")
    message_id = normalize_message_ref(row["message_id"])
    if message_id:
        keys.append(f"msg:{message_id}")

    normalized_body = fingerprint.normalized if fingerprint else canonical_body(row["body_text"])
    if len(normalized_body) >= 40:
        keys.append(f"body:{body_hash(normalized_body)}")
    if len(normalized_body) >= 160:
        keys.append(f"body_prefix:{body_hash(normalized_body[:240])}")

    subject = normalize_subject(row["subject"])
    sender = normalize_contact(row["from_addr"])
    if subject and sender:
        keys.append(f"subject_sender:{subject}|{sender}")

    date_bucket = duplicate_date_bucket(row["date_utc"])
    if subject and date_bucket is not None:
        keys.extend(
            f"subject_date:{subject}|{bucket}"
            for bucket in (date_bucket - 1, date_bucket, date_bucket + 1)
        )

    # Near-duplicate recall: bodies that share an LSH band collide here even
    # when their exact body / 240-char-prefix hashes differ.
    if fingerprint is not None:
        keys.extend(lsh_band_keys(fingerprint.signature))
    return keys


def duplicate_date_bucket(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value).timestamp() // 600)
    except ValueError:
        return None


def pending_duplicate_counts(
    conn: sqlite3.Connection, email_ids: Iterable[int]
) -> Dict[int, int]:
    ids = list(email_ids)
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT email_a_id, email_b_id
        FROM email_duplicate_candidates
        WHERE status = 'pending'
          AND (email_a_id IN ({placeholders}) OR email_b_id IN ({placeholders}))
        """,
        [*ids, *ids],
    ).fetchall()
    counts = {email_id: 0 for email_id in ids}
    for row in rows:
        if row["email_a_id"] in counts:
            counts[row["email_a_id"]] += 1
        if row["email_b_id"] in counts:
            counts[row["email_b_id"]] += 1
    return counts


def list_duplicate_candidates(
    case_id: int,
    *,
    email_id: Optional[int] = None,
    status: str = "pending",
) -> List[Dict[str, Any]]:
    clauses = ["case_id = ?", "status = ?"]
    params: List[Any] = [case_id, status]
    if email_id is not None:
        clauses.append("(email_a_id = ? OR email_b_id = ?)")
        params.extend([email_id, email_id])
    with db.get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM email_duplicate_candidates
            WHERE {" AND ".join(clauses)}
            ORDER BY score DESC, id ASC
            """,
            params,
        ).fetchall()
        return serialize_duplicate_candidates(conn, rows)


def _write_candidate_decision(
    conn: sqlite3.Connection,
    current: sqlite3.Row,
    *,
    status: str,
    canonical_email_id: Optional[int],
    duplicate_email_id: Optional[int],
) -> sqlite3.Row:
    """Apply a status decision to one candidate row, recording an audit event."""
    now = db.utc_now()
    decided_at = now if status != "pending" else None
    conn.execute(
        """
        UPDATE email_duplicate_candidates
        SET status = ?, canonical_email_id = ?, duplicate_email_id = ?,
            decided_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, canonical_email_id, duplicate_email_id, decided_at, now, current["id"]),
    )
    updated = conn.execute(
        "SELECT * FROM email_duplicate_candidates WHERE id = ?",
        (current["id"],),
    ).fetchone()
    record_audit_event(
        conn,
        case_id=updated["case_id"],
        action="email.duplicate_reviewed",
        entity_type="duplicate_candidate",
        entity_id=int(current["id"]),
        before=serialize_duplicate_candidate_core(current),
        after=serialize_duplicate_candidate_core(updated),
        metadata={
            "email_ids": [updated["email_a_id"], updated["email_b_id"]],
            "status": status,
        },
    )
    return updated


def update_duplicate_candidate(
    candidate_id: int,
    *,
    status: str,
    canonical_email_id: Optional[int] = None,
    duplicate_email_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    if status not in {"pending", "duplicate", "dissimilar"}:
        return None
    with db.get_conn() as conn:
        current = conn.execute(
            "SELECT * FROM email_duplicate_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if not current:
            return None
        pair_ids = {current["email_a_id"], current["email_b_id"]}
        if status == "duplicate":
            if canonical_email_id not in pair_ids or duplicate_email_id not in pair_ids:
                return None
            if canonical_email_id == duplicate_email_id:
                return None
        else:
            canonical_email_id = None
            duplicate_email_id = None

        updated = _write_candidate_decision(
            conn,
            current,
            status=status,
            canonical_email_id=canonical_email_id,
            duplicate_email_id=duplicate_email_id,
        )
        return serialize_duplicate_candidates(conn, [updated])[0]


def resolve_exact_duplicates(case_id: int) -> int:
    """Auto-mark every pending exact-match pair (same file/Message-ID/body)."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM email_duplicate_candidates
            WHERE case_id = ? AND status = 'pending'
            """,
            (case_id,),
        ).fetchall()
        exact_rows = [row for row in rows if reasons_are_exact(json_loads(row["reason_json"], []))]
        if not exact_rows:
            return 0
        email_ids = {
            email_id
            for row in exact_rows
            for email_id in (row["email_a_id"], row["email_b_id"])
        }
        emails_by_id = email_repo.serialized_emails_by_id(conn, sorted(email_ids))
        resolved = 0
        for row in exact_rows:
            a, b = row["email_a_id"], row["email_b_id"]
            members = [emails_by_id.get(a), emails_by_id.get(b)]
            canonical = suggest_canonical(members) or a
            duplicate = b if canonical == a else a
            _write_candidate_decision(
                conn,
                row,
                status="duplicate",
                canonical_email_id=canonical,
                duplicate_email_id=duplicate,
            )
            resolved += 1
        return resolved


def resolve_duplicate_cluster(
    case_id: int, canonical_email_id: int, member_email_ids: Iterable[int]
) -> int:
    """Keep canonical_email_id; mark the rest of the cluster as duplicates of it.

    Every pending pair fully inside the cluster is decided in one transaction.
    Pairs containing the canonical resolve against it; pairs between two
    non-canonical members are still recorded as duplicates of each other.
    """
    members = set(int(email_id) for email_id in member_email_ids) | {int(canonical_email_id)}
    if len(members) < 2:
        return 0
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM email_duplicate_candidates
            WHERE case_id = ? AND status = 'pending'
            """,
            (case_id,),
        ).fetchall()
        resolved = 0
        for row in rows:
            a, b = row["email_a_id"], row["email_b_id"]
            if a not in members or b not in members:
                continue
            if canonical_email_id in (a, b):
                canonical = canonical_email_id
                duplicate = b if a == canonical_email_id else a
            else:
                # Both members are duplicates of the cluster canonical; still
                # record this intra-cluster pair so it leaves the queue.
                canonical, duplicate = a, b
            _write_candidate_decision(
                conn,
                row,
                status="duplicate",
                canonical_email_id=canonical,
                duplicate_email_id=duplicate,
            )
            resolved += 1
        return resolved


def list_duplicate_clusters(case_id: int) -> List[Dict[str, Any]]:
    """Group pending candidate pairs into clusters via connected components."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM email_duplicate_candidates
            WHERE case_id = ? AND status = 'pending'
            ORDER BY score DESC, id ASC
            """,
            (case_id,),
        ).fetchall()
        if not rows:
            return []

        parent: Dict[int, int] = {}

        def find(node: int) -> int:
            parent.setdefault(node, node)
            root = node
            while parent[root] != root:
                root = parent[root]
            while parent[node] != root:
                parent[node], node = root, parent[node]
            return root

        def union(left: int, right: int) -> None:
            parent[find(left)] = find(right)

        for row in rows:
            union(row["email_a_id"], row["email_b_id"])

        groups: Dict[int, set] = {}
        pairs_by_group: Dict[int, List[sqlite3.Row]] = {}
        for row in rows:
            root = find(row["email_a_id"])
            groups.setdefault(root, set()).update((row["email_a_id"], row["email_b_id"]))
            pairs_by_group.setdefault(root, []).append(row)

        all_ids = sorted({email_id for ids in groups.values() for email_id in ids})
        emails_by_id = email_repo.serialized_emails_by_id(conn, all_ids)

        clusters: List[Dict[str, Any]] = []
        for root, ids in groups.items():
            member_ids = sorted(ids)
            members = [emails_by_id[email_id] for email_id in member_ids if email_id in emails_by_id]
            pairs = pairs_by_group[root]
            clusters.append(
                {
                    "id": f"cluster-{min(member_ids)}",
                    "email_ids": member_ids,
                    "candidate_ids": [int(pair["id"]) for pair in pairs],
                    "max_score": max(float(pair["score"]) for pair in pairs),
                    "suggested_canonical_id": suggest_canonical(members),
                    "emails": members,
                    "pairs": [
                        {
                            "email_a_id": pair["email_a_id"],
                            "email_b_id": pair["email_b_id"],
                            "score": float(pair["score"]),
                            "reasons": json_loads(pair["reason_json"], []),
                        }
                        for pair in pairs
                    ],
                }
            )
        clusters.sort(key=lambda cluster: cluster["max_score"], reverse=True)
        return clusters


def serialize_duplicate_candidate_core(row: sqlite3.Row) -> Dict[str, Any]:
    item = row_to_dict(row)
    item["reasons"] = json_loads(item.pop("reason_json", None), [])
    return item


def serialize_duplicate_candidates(
    conn: sqlite3.Connection, rows: Iterable[sqlite3.Row]
) -> List[Dict[str, Any]]:
    candidate_rows = list(rows)
    email_ids = sorted(
        {
            email_id
            for row in candidate_rows
            for email_id in (row["email_a_id"], row["email_b_id"])
        }
    )
    emails_by_id = email_repo.serialized_emails_by_id(conn, email_ids)
    result = []
    for row in candidate_rows:
        item = serialize_duplicate_candidate_core(row)
        item["email_a"] = emails_by_id.get(row["email_a_id"])
        item["email_b"] = emails_by_id.get(row["email_b_id"])
        result.append(item)
    return result
