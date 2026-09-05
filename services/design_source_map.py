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
from typing import Optional, Tuple

_SOURCE_EXTS = (".tsx", ".jsx", ".ts", ".js", ".html", ".vue")

# files never considered edit targets
_SKIP_DIRS = {"node_modules", "dist", "dist-da", ".git", "design", "public"}


@dataclass
class SourceMatch:
    file: str  # relative to frontend/ e.g. "src/components/Hero.tsx"
    confidence: str  # "data-da-source" | "classname" | "classname-partial" | "text"
    line: Optional[int] = None
    component: Optional[str] = None
    # The literal class attribute value found in the file — when the node's
    # runtime className differs (cn() merges, ordering), the patcher must
    # target THIS string instead of the bridge-reported one.
    class_in_file: Optional[str] = None
    # True when class_in_file is a conditional class STRING inside an
    # expression (cn(...), ternaries) rather than a className attribute —
    # the patcher then targets that string literal directly.
    class_span_is_string: bool = False


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


def _find_class_in_file(content: str, class_name: str, intent: dict = None) -> tuple:
    """Find the literal class string in this file matching the node's
    runtime className.

    Pass 1: className/class attributes (exact → token-overlap ≥0.7).
    Pass 2: string literals — conditional classes live in cn(...) / ternary
    strings. Scored category-aware: strings containing tokens in the SAME
    category as the style intent (e.g. a text-color token when changing
    color) win, so an ACTIVE-state string beats the base class string.

    Returns (literal, is_string_span)."""
    if f'"{class_name}"' in content or f"'{class_name}'" in content:
        return class_name, False
    node_tokens = set(class_name.split())
    if len(node_tokens) < 2:
        return None, False

    # categories the intent will touch
    from services.design_tailwind_patch import classify_token
    _INTENT_PREFIX_CATS = {
        "bg-": "bg-color", "text-": "text-color", "color": "text-color",
        "background": "bg-color", "backgroundColor": "bg-color",
        "fontSize": "text-size", "fontWeight": "font-weight",
        "padding": "padding", "margin": "margin", "borderRadius": "radius",
        "opacity": "opacity", "width": "width", "maxWidth": "max-width",
        "height": "height",
    }
    intent_cats = set()
    for prop in (intent or {}):
        cat = _INTENT_PREFIX_CATS.get(prop)
        if cat:
            intent_cats.add(cat)

    def conflict_score(tokens):
        for t in tokens:
            cat = classify_token(t)
            if cat and cat in intent_cats:
                return 1
        return 0

    best = None  # (conflict, containment, overlap, literal, is_string)
    _attr_re = re.compile(r'(?:className|class)=["\']([^"\']*)["\']')
    _any_str_re = re.compile(r'["\']([^"\'\n]{8,240})["\']')
    for pass_is_string, rex in ((False, _attr_re), (True, _any_str_re)):
        for m in rex.finditer(content):
            s_tokens = set(m.group(1).split())
            if len(s_tokens) < 2:
                continue
            overlap = node_tokens & s_tokens
            if len(overlap) < 2:
                continue
            containment = len(overlap) / len(s_tokens)
            if containment < 0.6:
                continue
            conflict = conflict_score(s_tokens) if pass_is_string else 0
            score = (conflict, containment, len(overlap))
            if best is None or score > best[:3]:
                best = (conflict, containment, len(overlap), m.group(1), pass_is_string)
    if best:
        return best[3], best[4]
    return None, False


def resolve_node_file(
    frontend_path: Path,
    node: dict,
    style_intent: dict = None,
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
            class_in_file, span_is_string = None, False
            if class_name:
                try:
                    class_in_file, span_is_string = _find_class_in_file(
                        candidate.read_text(encoding="utf-8", errors="ignore"), class_name, style_intent
                    )
                except OSError:
                    class_in_file, span_is_string = None, False
            return SourceMatch(file=rel, confidence="data-da-source",
                               component=source.get("component"),
                               class_in_file=class_in_file,
                               class_span_is_string=span_is_string)
        # try to find by basename when the recorded path drifted
        base = Path(rel).name
        for f in _iter_source_files(frontend_path):
            if f.name == base:
                class_in_file, span_is_string = None, False
                if class_name:
                    try:
                        class_in_file, span_is_string = _find_class_in_file(
                            f.read_text(encoding="utf-8", errors="ignore"), class_name, style_intent
                        )
                    except OSError:
                        class_in_file, span_is_string = None, False
                return SourceMatch(file=_to_rel(f, frontend_path),
                                   confidence="data-da-source",
                                   component=source.get("component"),
                                   class_in_file=class_in_file,
                                   class_span_is_string=span_is_string)

    files = list(_iter_source_files(frontend_path))
    if not files:
        return None

    if class_name:
        # 2a. exact className match. shadcn primitives (components/ui/*) are
        # excluded — a className literal there is a variant definition, and
        # patching it would restyle every instance of that primitive.
        needle = class_name
        hits = []
        for f in files:
            rel_f = _to_rel(f, frontend_path)
            if rel_f.startswith("src/components/ui/"):
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if f'"{needle}"' in content or f"'{needle}'" in content:
                hits.append((f, needle))
        if len(hits) == 1:
            f, attr = hits[0]
            return SourceMatch(file=_to_rel(f, frontend_path), confidence="classname",
                               class_in_file=attr)
        if len(hits) > 1:
            # prefer files under src/components or src/pages
            ranked = [h for h in hits if "/src/" in _to_rel(h[0], frontend_path)] or hits
            f, attr = ranked[0]
            return SourceMatch(file=_to_rel(f, frontend_path), confidence="classname",
                               class_in_file=attr)

        # 2b. token-overlap match — runtime classNames often differ from the
        # source literal (cn() merges, class ordering, appended state classes).
        # Find the className attribute whose token set overlaps the node's
        # strongly; require a single best file. shadcn primitives
        # (components/ui/*) are excluded — patching a variant there would
        # restyle every instance of that primitive.
        node_tokens = set(class_name.split())
        if len(node_tokens) >= 2:
            _attr_re = re.compile(r'(?:className|class)=["\']([^"\']*)["\']')
            best_per_file = []  # (score, overlap, file, attr_value)
            for f in files:
                rel_f = _to_rel(f, frontend_path)
                if rel_f.startswith("src/components/ui/"):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                best = None
                for m in _attr_re.finditer(content):
                    attr_tokens = set(m.group(1).split())
                    if len(attr_tokens) < 2:
                        continue
                    overlap = node_tokens & attr_tokens
                    if len(overlap) < 2:
                        continue
                    score = len(overlap) / max(len(node_tokens), len(attr_tokens))
                    if best is None or score > best[0]:
                        best = (score, len(overlap), m.group(1))
                if best and best[0] >= 0.7:
                    best_per_file.append((best[0], best[1], f, best[2]))
            if best_per_file:
                best_per_file.sort(key=lambda t: (-t[0], -t[1], _to_rel(t[2], frontend_path)))
                top = best_per_file[0]
                # a close runner-up in a different file = ambiguous → skip
                runners = [b for b in best_per_file[1:] if b[2] != top[2] and b[0] >= top[0] - 0.05]
                if not runners:
                    return SourceMatch(
                        file=_to_rel(top[2], frontend_path),
                        confidence="classname-partial",
                        class_in_file=top[3],
                    )

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
