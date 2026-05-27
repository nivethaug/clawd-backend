"""Machine-readable workflow metadata for prompts sent to ClaudeCodeAgent."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional


META_START = "<DREAMPILOT_WORKFLOW_META>"
META_END = "</DREAMPILOT_WORKFLOW_META>"
SCHEMA = "dream.workflow.v1"

PROJECT_TYPES = {
    1: "website",
    2: "telegram",
    3: "discord",
    5: "scheduler",
    6: "custom",
}


def project_type_from_id(project_type_id: Optional[int], fallback: str = "unknown") -> str:
    try:
        return PROJECT_TYPES.get(int(project_type_id), fallback)
    except Exception:
        return fallback


def _clean_path(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _canonical_json(meta: Dict[str, Any]) -> str:
    payload = {key: value for key, value in meta.items() if key != "checksum" and value is not None}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def checksum_workflow_meta(meta: Dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(meta).encode("utf-8")).hexdigest()


def build_workflow_meta(
    *,
    project_type_id: Optional[int],
    project_type: Optional[str] = None,
    operation: str,
    workflow: Optional[str] = None,
    project_name: Optional[str] = None,
    project_id: Optional[int] = None,
    project_path: Optional[Any] = None,
    domain: Optional[str] = None,
    frontend_path: Optional[Any] = None,
    service_path: Optional[Any] = None,
    prompt_kind: Optional[str] = None,
    source: str = "db",
) -> Dict[str, Any]:
    resolved_type = (project_type or project_type_from_id(project_type_id)).strip().lower()
    resolved_operation = str(operation or "unknown").strip().lower()
    meta: Dict[str, Any] = {
        "schema": SCHEMA,
        "project_type": resolved_type,
        "project_type_id": project_type_id,
        "operation": resolved_operation,
        "workflow": workflow or f"{resolved_type}_{resolved_operation}",
        "prompt_kind": prompt_kind,
        "project_name": project_name,
        "project_id": project_id,
        "project_path": _clean_path(project_path),
        "frontend_path": _clean_path(frontend_path),
        "service_path": _clean_path(service_path),
        "domain": domain,
        "source": source,
    }
    meta["checksum"] = checksum_workflow_meta(meta)
    return {key: value for key, value in meta.items() if value is not None}


def build_workflow_meta_block(**kwargs: Any) -> str:
    meta = build_workflow_meta(**kwargs)
    return (
        f"{META_START}\n"
        f"{json.dumps(meta, sort_keys=True, indent=2, ensure_ascii=True)}\n"
        f"{META_END}\n"
    )
