import sqlite3
from typing import Dict, Optional

from ..services.text_norm import (
    conversation_index_root,
    fallback_thread_key,
    json_loads,
    normalize_message_ref,
)


def recompute_case_threads(conn: sqlite3.Connection, case_id: int) -> None:
    rows = conn.execute(
        """
        SELECT id, message_id, in_reply_to, references_json, subject,
               source_kind, parent_email_id, thread_id,
               conversation_index, conversation_topic
        FROM emails
        WHERE case_id = ?
        ORDER BY COALESCE(date_utc, created_at) ASC, id ASC
        """,
        (case_id,),
    ).fetchall()
    if not rows:
        return

    email_by_message_id = {}
    row_by_id = {}
    for row in rows:
        row_by_id[row["id"]] = row
        message_id = normalize_message_ref(row["message_id"])
        if message_id:
            email_by_message_id[message_id] = row["id"]

    parent_by_id: Dict[int, Optional[int]] = {}
    explicit_root_ref_by_id: Dict[int, Optional[str]] = {}
    for row in rows:
        refs = [normalize_message_ref(ref) for ref in json_loads(row["references_json"], [])]
        refs = [ref for ref in refs if ref]
        in_reply_to = normalize_message_ref(row["in_reply_to"])
        parent_ref = in_reply_to or (refs[-1] if refs else None)
        header_parent_id = email_by_message_id.get(parent_ref) if parent_ref else None
        existing_parent_id = (
            row["parent_email_id"] if row["source_kind"] in {"quoted", "attached", "snipped"} else None
        )
        parent_by_id[row["id"]] = header_parent_id or existing_parent_id
        explicit_root_ref_by_id[row["id"]] = refs[0] if refs else None

    memo: Dict[int, str] = {}

    def thread_key(row_id: int, stack: Optional[set] = None) -> str:
        if row_id in memo:
            return memo[row_id]
        if stack is None:
            stack = set()
        if row_id in stack:
            row = row_by_id[row_id]
            return fallback_thread_key(row)
        stack.add(row_id)

        row = row_by_id[row_id]
        explicit_root_ref = explicit_root_ref_by_id.get(row_id)
        # Outlook conversation root: groups .msg replies that carry no
        # In-Reply-To/References (so no header parent resolves and there is no
        # root ref) but share a Conversation-Index, which RFC-threaded mail lacks.
        conversation_root = conversation_index_root(row["conversation_index"])
        if parent_by_id.get(row_id):
            key = thread_key(parent_by_id[row_id], stack)
        elif explicit_root_ref:
            key = f"msg:{explicit_root_ref}"
        elif conversation_root:
            key = f"convidx:{conversation_root}"
        else:
            message_id = normalize_message_ref(row["message_id"])
            key = f"msg:{message_id}" if message_id else fallback_thread_key(row)

        memo[row_id] = key
        return key

    # Only write rows whose thread_id/parent_email_id actually change. A single
    # appended email leaves most of the case untouched, so this avoids rewriting
    # every row (and the audit/index churn that comes with it).
    for row in rows:
        new_thread_id = thread_key(row["id"])
        new_parent_id = parent_by_id[row["id"]]
        if new_thread_id == row["thread_id"] and new_parent_id == row["parent_email_id"]:
            continue
        conn.execute(
            "UPDATE emails SET thread_id = ?, parent_email_id = ? WHERE id = ?",
            (new_thread_id, new_parent_id, row["id"]),
        )
