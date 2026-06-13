import sqlite3
from datetime import datetime
from typing import Optional


def repair_case_dates(conn: sqlite3.Connection, case_id: int) -> int:
    case = conn.execute("SELECT default_tz FROM cases WHERE id = ?", (case_id,)).fetchone()
    default_tz = (case["default_tz"] if case else None) or "UTC"

    from ..services.dates import to_utc

    rows = conn.execute(
        """
        SELECT id, source_kind, date_raw, date_utc, body_text
        FROM emails
        WHERE case_id = ?
        """,
        (case_id,),
    ).fetchall()
    updated = 0
    for row in rows:
        if is_valid_iso_datetime(row["date_utc"]):
            continue
        date_raw = row["date_raw"] or row["date_utc"] or leading_embedded_date(row["body_text"] or "")
        iso = to_utc(date_raw, default_tz)
        if iso:
            conn.execute(
                "UPDATE emails SET date_raw = COALESCE(date_raw, ?), date_utc = ? WHERE id = ?",
                (date_raw, iso, row["id"]),
            )
        elif row["date_utc"] is not None:
            conn.execute("UPDATE emails SET date_utc = NULL WHERE id = ?", (row["id"],))
        else:
            continue
        updated += 1
    return updated


def is_valid_iso_datetime(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def leading_embedded_date(body_text: str) -> Optional[str]:
    from ..services.quotes import match_cjk_header, parse_header_line

    for line in body_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")[:12]:
        stripped = line.strip()
        if not stripped:
            continue
        header = match_cjk_header(stripped) or parse_header_line(stripped)
        if header and header[0] in {"sent", "date"}:
            return header[1]
    return None
