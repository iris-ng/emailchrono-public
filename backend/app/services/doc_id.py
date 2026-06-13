"""Human-facing per-email document identifiers.

Each email row carries a short random code (``doc_id``) that is unique within its
case, used for citation in exports and the chronology UI. The integer primary key
remains the internal identifier; this is purely the user-facing handle.

The alphabet omits visually ambiguous characters (0/O, 1/I/L) so codes survive
being read aloud or copied from a printed brief.
"""

import secrets
import sqlite3

DOC_ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
DOC_ID_LENGTH = 5
_MAX_ATTEMPTS = 25


def generate_doc_id(length: int = DOC_ID_LENGTH) -> str:
    return "".join(secrets.choice(DOC_ID_ALPHABET) for _ in range(length))


def allocate_doc_id(conn: sqlite3.Connection, case_id: int) -> str:
    """Return a doc_id not yet used in ``case_id``.

    Writes are serialized through a single connection per transaction, so a
    SELECT-then-INSERT in the same transaction is race-free; the
    ``UNIQUE(case_id, doc_id)`` index is the ultimate backstop. After many
    attempts (an effectively saturated case) we widen the code rather than loop
    forever."""
    for attempt in range(_MAX_ATTEMPTS):
        candidate = generate_doc_id(DOC_ID_LENGTH + attempt // _MAX_ATTEMPTS)
        exists = conn.execute(
            "SELECT 1 FROM emails WHERE case_id = ? AND doc_id = ? LIMIT 1",
            (case_id, candidate),
        ).fetchone()
        if not exists:
            return candidate
    return generate_doc_id(DOC_ID_LENGTH + 2)


def backfill_doc_ids(conn: sqlite3.Connection) -> int:
    """Assign a doc_id to every email still missing one. Idempotent: only touches
    rows where ``doc_id IS NULL``, so it is safe to run on every startup."""
    rows = conn.execute(
        "SELECT id, case_id FROM emails WHERE doc_id IS NULL ORDER BY case_id, id"
    ).fetchall()
    for row in rows:
        doc_id = allocate_doc_id(conn, row["case_id"])
        conn.execute("UPDATE emails SET doc_id = ? WHERE id = ?", (doc_id, row["id"]))
    return len(rows)
