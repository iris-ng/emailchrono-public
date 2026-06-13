import sqlite3
from typing import Sequence

from .. import db
from ..services.audit import record_audit_event


def update_manual_chain_order(case_id: int, email_ids: Sequence[int]) -> bool:
    if not email_ids:
        return False
    unique_ids = []
    seen = set()
    for email_id in email_ids:
        if email_id in seen:
            continue
        seen.add(email_id)
        unique_ids.append(email_id)

    placeholders = ",".join("?" for _ in unique_ids)
    with db.get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, thread_id
            FROM emails
            WHERE case_id = ? AND deleted_at IS NULL AND id IN ({placeholders})
            """,
            [case_id, *unique_ids],
        ).fetchall()
        if len(rows) != len(unique_ids):
            return False
        thread_ids = {row["thread_id"] or f"email:{row['id']}" for row in rows}
        if len(thread_ids) > 1:
            return False
        previous_order_rows = conn.execute(
            """
            SELECT id
            FROM emails
            WHERE case_id = ? AND deleted_at IS NULL
              AND COALESCE(thread_id, 'email:' || id) = ?
            ORDER BY
              CASE WHEN manual_chain_order IS NULL THEN 1 ELSE 0 END ASC,
              manual_chain_order ASC,
              COALESCE(date_utc, created_at) ASC,
              id ASC
            """,
            (case_id, next(iter(thread_ids))),
        ).fetchall()
        previous_order = [row["id"] for row in previous_order_rows]
        for index, email_id in enumerate(unique_ids):
            conn.execute(
                "UPDATE emails SET manual_chain_order = ? WHERE case_id = ? AND id = ?",
                (index, case_id, email_id),
            )
        record_audit_event(
            conn,
            case_id=case_id,
            action="email.chain_order_changed",
            entity_type="thread",
            before={"email_ids": previous_order},
            after={"email_ids": unique_ids},
            metadata={"thread_id": next(iter(thread_ids))},
        )
        conn.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (db.utc_now(), case_id))
    return True


def update_manual_chronology_order(case_id: int, email_ids: Sequence[int]) -> bool:
    unique_ids = []
    seen = set()
    for email_id in email_ids:
        if email_id in seen:
            continue
        seen.add(email_id)
        unique_ids.append(email_id)

    with db.get_conn() as conn:
        case = conn.execute("SELECT id FROM cases WHERE id = ?", (case_id,)).fetchone()
        if not case:
            return False

        case_rows = conn.execute(
            "SELECT id FROM emails WHERE case_id = ? AND deleted_at IS NULL ORDER BY id",
            (case_id,),
        ).fetchall()
        case_ids = [row["id"] for row in case_rows]

        if not unique_ids:
            previous_rows = conn.execute(
                """
                SELECT id
                FROM emails
                WHERE case_id = ? AND deleted_at IS NULL
                ORDER BY
                  CASE WHEN manual_chrono_order IS NULL THEN 1 ELSE 0 END ASC,
                  manual_chrono_order ASC,
                  COALESCE(date_utc, created_at) ASC,
                  id ASC
                """,
                (case_id,),
            ).fetchall()
            conn.execute(
                "UPDATE emails SET manual_chrono_order = NULL WHERE case_id = ?",
                (case_id,),
            )
            record_audit_event(
                conn,
                case_id=case_id,
                action="email.chronology_order_reset",
                entity_type="case",
                entity_id=case_id,
                before={"email_ids": [row["id"] for row in previous_rows]},
                after={"email_ids": []},
            )
            conn.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (db.utc_now(), case_id))
            return True

        if set(unique_ids) != set(case_ids):
            return False

        previous_rows = conn.execute(
            """
            SELECT id
            FROM emails
            WHERE case_id = ? AND deleted_at IS NULL
            ORDER BY
              CASE WHEN manual_chrono_order IS NULL THEN 1 ELSE 0 END ASC,
              manual_chrono_order ASC,
              COALESCE(date_utc, created_at) ASC,
              id ASC
            """,
            (case_id,),
        ).fetchall()

        for index, email_id in enumerate(unique_ids):
            conn.execute(
                "UPDATE emails SET manual_chrono_order = ? WHERE case_id = ? AND id = ?",
                (index, case_id, email_id),
            )
        record_audit_event(
            conn,
            case_id=case_id,
            action="email.chronology_order_changed",
            entity_type="case",
            entity_id=case_id,
            before={"email_ids": [row["id"] for row in previous_rows]},
            after={"email_ids": unique_ids},
        )
        conn.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (db.utc_now(), case_id))
    return True
