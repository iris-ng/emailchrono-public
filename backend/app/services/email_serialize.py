import sqlite3
from typing import Any, Dict, List, Optional

from .text_norm import (
    fallback_thread_key,
    json_loads,
    normalize_message_ref,
    normalize_subject,
    row_to_dict,
)


def default_boundary_method(item: Dict[str, Any]) -> str:
    if item.get("source_import_mode") == "manual":
        return "manual"
    source_kind = item.get("source_kind")
    if source_kind == "attached":
        return "attached_email"
    if source_kind == "quoted":
        return "quoted_text"
    return "mime"


def default_relation_confidence(item: Dict[str, Any]) -> str:
    # An attached email's parent/child link is certain (it came out of the file),
    # so the relation is high-confidence even if its own parse_confidence is lower.
    if item.get("source_kind") == "attached":
        return "high"
    if item.get("source_kind") == "quoted" or item.get("parse_confidence") == "low":
        return "low"
    return "high"


def serialize_email(
    row: sqlite3.Row,
    attachments: List[Dict[str, Any]],
    chain_date_conflict: bool = False,
    suspected_duplicate_count: int = 0,
    tags: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    item = row_to_dict(row)
    item["references"] = json_loads(item.pop("references_json", None), [])
    item["to"] = json_loads(item.pop("to_json", None), [])
    item["cc"] = json_loads(item.pop("cc_json", None), [])
    raw_json = json_loads(item.get("raw_json"), {})
    flags = item.pop("flags", None)
    item["flags"] = [flag for flag in (flags or "").split(",") if flag]
    item["chain_date_conflict"] = chain_date_conflict
    if chain_date_conflict and "chain_date_conflict" not in item["flags"]:
        item["flags"].append("chain_date_conflict")
    item["user_edited"] = bool(item["user_edited"])
    item["source_openable"] = bool(item["source_openable"])
    item["important"] = bool(item.get("important"))
    item["suspected_duplicate_count"] = suspected_duplicate_count
    item["attachments"] = attachments
    item["tags"] = tags or []
    item["boundary_method"] = raw_json.get(
        "boundary_method",
        default_boundary_method(item),
    )
    item["boundary_evidence"] = raw_json.get("boundary_evidence", [])
    item["relation_confidence"] = raw_json.get(
        "relation_confidence",
        default_relation_confidence(item),
    )
    item["relation_thread_id"] = item.get("thread_id") or f"email:{item['id']}"
    item["relation_parent_id"] = item.get("parent_email_id")
    item["relation_source_id"] = item.get("chain_source_id") or item["id"]
    item["relation_refs"] = {
        "message_id": normalize_message_ref(item.get("message_id")),
        "in_reply_to": normalize_message_ref(item.get("in_reply_to")),
        "references": [
            ref for ref in (normalize_message_ref(ref) for ref in item["references"]) if ref
        ],
    }
    item.pop("source_file", None)
    item["raw_json"] = {}
    item["body_html_raw"] = ""
    return item
