"""
Element → source-file mapping for the design layer.

Resolution order (first success wins):
  1. data-da-source attribute (bridge reports it via node.source.file)
  2. exact className grep across frontend/src
  3. unique text-literal grep across frontend/src
  4. unmapped → caller routes to the agent (Path B)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

_SOURCE_EXTS = (".tsx", ".jsx", ".ts", ".js", ".html", ".vue")

# files never considered edit targets
_SKIP_DIRS = {"node_modules", "dist", "dist-da", ".git", "design", "public"}


@dataclass
class SourceMatch:
    file: str  # relative to frontend/ e.g. "src/components/Hero.tsx"
    confidence: str  # "data-da-source" | "classname" | "text"
    line: Optional[int] = None
    component: Optional[str] = None


def _iter_source_files(frontend_path: Path):
    if not frontend_path.is_dir():
        return
    for root, dirs, files in os.walk(frontend_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name.endswith(_SOURCE_EXTS):
                yield Path(root) / name


def _to_rel(p: Path, frontend_path: Path) -> str:
    return p.relative_to(frontend_path).as_posix()


def resolve_node_file(
    frontend_path: Path,
    node: dict,
) -> Optional[SourceMatch]:
    """Map a bridge DesignNode to a source file under frontend/."""
    frontend_path = Path(frontend_path)
    if not frontend_path.is_dir():
        return None

    source = (node or {}).get("source") or {}
    class_name = (node.get("className") or "").strip()
    text_preview = (node.get("textPreview") or "").strip()

    # 1. data-da-source
    rel = (source.get("file") or "").strip().strip("/")
    if rel:
        rel = re.sub(r"^frontend/", "", rel)  # tolerate full repo-relative paths
        # never honor traversal attempts from page attributes
        if "\\" in rel or ".." in PurePosixPath(rel).parts or rel.startswith("/"):
            rel = ""
    if rel:
        candidate = frontend_path / rel
        if candidate.is_file():
            return SourceMatch(file=rel, confidence="data-da-source",
                               component=source.get("component"))
        # try to find by basename when the recorded path drifted
        base = Path(rel).name
        for f in _iter_source_files(frontend_path):
            if f.name == base:
                return SourceMatch(file=_to_rel(f, frontend_path),
                                   confidence="data-da-source",
                                   component=source.get("component"))

    files = list(_iter_source_files(frontend_path))
    if not files:
        return None

    # 2. exact className match
    if class_name:
        needle = class_name
        hits = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if f'"{needle}"' in content or f"'{needle}'" in content:
                hits.append(f)
        if len(hits) == 1:
            return SourceMatch(file=_to_rel(hits[0], frontend_path), confidence="classname")
        if len(hits) > 1:
            # prefer files under src/components or src/pages
            ranked = [h for h in hits if "/src/" in _to_rel(h, frontend_path)] or hits
            return SourceMatch(file=_to_rel(ranked[0], frontend_path), confidence="classname")

    # 3. unique text literal
    if text_preview and len(text_preview) >= 4:
        hits = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if text_preview in content:
                hits.append(f)
        if len(hits) == 1:
            return SourceMatch(file=_to_rel(hits[0], frontend_path), confidence="text")

    return None
