"""
Tailwind class translation for the design layer (Path A).

Translates a CSS style intent (property → value, straight from the design
panel / bridge computed styles) into className edits on the target element
in a source file. Never rewrites the whole file — only the target
element's class list (or a unique text literal for text edits).

Strategy:
- Locate the element's className="..." occurrence by (in order):
    1. exact className match
    2. textPreview literal → nearest preceding className attribute
- Map intent properties to Tailwind utility categories and emit
  arbitrary-value utilities (bg-[#rrggbb], p-[24px], ...) so no palette
  lookup is needed. An existing utility in the same category is REPLACED
  (bg-red-500 → bg-[#2563eb]); otherwise the utility is appended.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Named Tailwind color families (for classifying existing text-* tokens
# as COLOR rather than SIZE).
_COLOR_FAMILIES = (
    "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|"
    "emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|"
    "inherit|current|transparent|black|white"
)
_SIZE_WORDS = "xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl|8xl|9xl"

# Category regexes — a token is classified into AT MOST one bucket.
_CATEGORY_RES: Dict[str, re.Pattern] = {
    "bg-color": re.compile(rf"^bg-({_COLOR_FAMILIES})(-\d{{2,3}})?$|^bg-\["),
    "text-color": re.compile(rf"^text-({_COLOR_FAMILIES})(-\d{{2,3}})?$|^text-\[#"),
    "text-size": re.compile(rf"^text-({_SIZE_WORDS})$|^text-\[\d+(?:\.\d+)?(?:px|rem|em)\]$"),
    "font-weight": re.compile(r"^font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$|^font-\[\d{3}\]$"),
    "font-family": re.compile(r"^font-(sans|serif|mono)$|^font-\[.+?\]$"),
    "padding": re.compile(r"^(p|px|py|pt|pb|pl|pr)-"),
    "margin": re.compile(r"^(m|mx|my|mt|mb|ml|mr)-"),
    "radius": re.compile(r"^rounded($|-[a-z0-9]+$)|^rounded-\["),
    "shadow": re.compile(r"^shadow($|-[a-z0-9]+$)"),
    "opacity": re.compile(r"^opacity-"),
    "width": re.compile(r"^w-"),
    "max-width": re.compile(r"^max-w-"),
    "height": re.compile(r"^h-"),
    "letter-spacing": re.compile(r"^tracking-"),
    "line-height": re.compile(r"^leading-"),
    "text-align": re.compile(r"^text-(left|center|right|justify|start|end)$"),
}

# intent property → (utility prefix builder, category)
_INTENT_MAP: Dict[str, Tuple[str, str]] = {
    "background": ("bg-", "bg-color"),
    "backgroundColor": ("bg-", "bg-color"),
    "color": ("text-", "text-color"),
    "fontSize": ("text-", "text-size"),
    "fontWeight": ("font-", "font-weight"),
    "fontFamily": ("font-", "font-family"),
    "padding": ("p-", "padding"),
    "margin": ("m-", "margin"),
    "borderRadius": ("rounded-", "radius"),
    "opacity": ("opacity-", "opacity"),
    "width": ("w-", "width"),
    "maxWidth": ("max-w-", "max-width"),
    "height": ("h-", "height"),
    "letterSpacing": ("tracking-", "letter-spacing"),
    "lineHeight": ("leading-", "line-height"),
    "textAlign": ("text-", "text-align"),
}

# CSS color functions → hex
_RGB_RE = re.compile(r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")


class PatchError(Exception):
    """Raised when the patch cannot be applied safely."""


@dataclass
class ClassPatchResult:
    new_content: str
    changed: bool
    utility: str
    replaced: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def normalize_css_value(value: str) -> str:
    """rgb(a)/named → bracket-safe Tailwind arbitrary value body."""
    v = (value or "").strip()
    m = _RGB_RE.match(v)
    if m:
        r, g, b = (int(x) for x in m.groups())
        return "#{:02x}{:02x}{:02x}".format(r, g, b)
    # strip spaces (arbitrary values cannot contain raw spaces)
    return v.replace(" ", "")


def classify_token(token: str) -> Optional[str]:
    for cat, rex in _CATEGORY_RES.items():
        if rex.match(token):
            return cat
    return None


def _quote_re(attr: str) -> re.Pattern:
    return re.compile(rf'{attr}\s*=\s*"([^"]*)"')


def locate_class_attributes(
    content: str,
    class_name: Optional[str],
    text_preview: Optional[str],
    max_occurrences: int = 25,
) -> List[Tuple[int, int, str]]:
    """Find (start, end, current_value) spans of the target element's class attr.

    Order: exact className match → text literal with nearest preceding class
    attribute. All occurrences of an identical className are returned (same
    class ⇒ same style — multi-select of same-class elements updates them
    together). Raises PatchError when nothing is found or the file is too
    repetitive to patch safely.
    """
    candidates: List[Tuple[int, int, str]] = []

    if class_name:
        needle = class_name.strip()
        if needle:
            for attr in ("className", "class"):
                for m in _quote_re(attr).finditer(content):
                    if m.group(1).strip() == needle:
                        candidates.append((m.start(1), m.end(1), m.group(1)))

    if not candidates and text_preview:
        needle = text_preview.strip()
        if needle:
            pos = content.find(needle)
            if pos != -1 and content.find(needle, pos + 1) == -1:
                # unique text literal — nearest class attr before it
                window = content[max(0, pos - 600) : pos]
                best = None
                for attr in ("className", "class"):
                    for m in _quote_re(attr).finditer(window):
                        best = (m.start(1), m.end(1), m.group(1))
                if best:
                    off = max(0, pos - 600)
                    candidates.append((off + best[0], off + best[1], best[2]))

    if not candidates:
        raise PatchError(
            "Could not locate the element in source (no unique className or text match)."
        )
    if len(candidates) > max_occurrences:
        raise PatchError(
            f"Element matches {len(candidates)} class attributes in this file — "
            "too ambiguous for a direct patch."
        )
    return candidates


def _uniform_padding(value: str, notes: List[str]) -> Optional[str]:
    """'16px 16px 16px 16px' → '16px'; None when sides differ."""
    parts = value.split()
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 4 and len(set(parts)) == 1:
        return parts[0]
    if len(parts) == 2:
        notes.append("Mixed padding sides — using vertical value for p-[].")
        return parts[0]
    notes.append("Mixed padding sides — using first value for p-[].")
    return parts[0]


def apply_style_intent(
    content: str,
    class_name: Optional[str],
    text_preview: Optional[str],
    intent: Dict[str, str],
) -> ClassPatchResult:
    """Apply a style intent to the located element's class list.

    All occurrences of an identical className are rewritten (multi-select of
    same-class elements updates together). Spans are replaced right-to-left
    so earlier offsets stay valid.
    """
    notes: List[str] = []
    spans = locate_class_attributes(content, class_name, text_preview)
    current = spans[0][2]
    tokens = current.split()
    changed_any = False
    last_utility = ""

    for prop in sorted(intent.keys()):
        value = intent[prop]
        if prop not in _INTENT_MAP:
            notes.append(f"Unsupported property: {prop}")
            continue
        prefix, category = _INTENT_MAP[prop]

        if prop in ("padding", "margin"):
            value = _uniform_padding(value, notes)
            if value is None:
                continue
        if value in ("", None):
            continue

        utility = f"{prefix}[{normalize_css_value(str(value))}]"

        # replace ALL tokens in the category — first gets the utility, the
        # rest are dropped (py-20 px-6 + uniform p-[24px] → single utility)
        replaced_tok = None
        rewritten: List[str] = []
        for tok in tokens:
            if classify_token(tok) == category:
                if replaced_tok is None:
                    rewritten.append(utility)
                    replaced_tok = tok
                # duplicate category token — dropped
            else:
                rewritten.append(tok)
        tokens = rewritten
        if replaced_tok is None:
            tokens.append(utility)
        changed_any = True
        last_utility = utility

    if not changed_any:
        raise PatchError("No applicable style properties in the intent.")

    new_class = " ".join(t for t in tokens if t)
    new_content = content
    for start, end, _ in sorted(spans, key=lambda s: s[0], reverse=True):
        new_content = new_content[:start] + new_class + new_content[end:]
    return ClassPatchResult(
        new_content=new_content,
        changed=True,
        utility=last_utility,
        notes=notes,
    )


def apply_text_change(
    content: str, before: str, after: str
) -> str:
    """Replace a text literal; requires exactly one occurrence."""
    if not before:
        raise PatchError("Empty 'before' text.")
    count = content.count(before)
    if count == 0:
        raise PatchError("Text not found in the mapped source file.")
    if count > 1:
        raise PatchError(f"Text appears {count} times — too ambiguous for a direct edit.")
    return content.replace(before, after, 1)
