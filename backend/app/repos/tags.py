"""Thin connection-managing wrappers over services.tags (which holds the
table logic). Routers call these so they don't manage transactions directly.
"""

import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from .. import db
from ..services import tags as tag_service


def list_tags(case_id: int) -> List[Dict[str, Any]]:
    with db.get_conn() as conn:
        return tag_service.list_tags(conn, case_id)


def get_tag(conn: sqlite3.Connection, tag_id: int) -> Optional[Dict[str, Any]]:
    return tag_service.get_tag(conn, tag_id)


def create_tag(case_id: int, name: str, color: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        return tag_service.create_tag(conn, case_id, name, color)


def update_tag(
    tag_id: int, *, name: Optional[str] = None, color: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        return tag_service.update_tag(conn, tag_id, name=name, color=color)


def delete_tag(tag_id: int) -> bool:
    with db.get_conn() as conn:
        return tag_service.delete_tag(conn, tag_id)


def tags_for_emails(
    conn: sqlite3.Connection, email_ids: Iterable[int]
) -> Dict[int, List[Dict[str, Any]]]:
    return tag_service.tags_for_emails(conn, email_ids)


def add_tags_to_emails(case_id: int, email_ids: List[int], tag_ids: List[int]) -> int:
    with db.get_conn() as conn:
        return tag_service.add_tags_to_emails(conn, case_id, email_ids, tag_ids)


def remove_tags_from_emails(case_id: int, email_ids: List[int], tag_ids: List[int]) -> int:
    with db.get_conn() as conn:
        return tag_service.remove_tags_from_emails(conn, case_id, email_ids, tag_ids)
