#!/usr/bin/env python3
"""Scrub TOOL:/PROGRESS:/TEXT: noise from already-saved assistant messages.

The chunk-filter bug (fixed in commit 054ec88) allowed TOOL:Read, TOOL:Bash,
PROGRESS:, etc. telemetry to leak into saved assistant messages. This script
cleans up those legacy rows so the chat history reads naturally.

Usage:
    # Dry run — show what would change, modify nothing
    python3 scripts/cleanup_tool_noise.py --dry-run

    # Apply the cleanup
    python3 scripts/cleanup_tool_noise.py

    # Limit to a specific session
    python3 scripts/cleanup_tool_noise.py --session-id 211

    # Limit to messages from the last N days
    python3 scripts/cleanup_tool_noise.py --since-days 7

What gets removed (per line):
    - TOOL:<anything>            (tool-call telemetry)
    - PROGRESS:<anything>        (friendly progress messages)
    - TEXT:                      (prefix-only lines with no actual content)
    - bare telemetry tokens      ('null', '{}', '[]', '---')
    - **Input:** / **Output:**   (MCP tool markers)
    - Stray ``` or ```json fence openers with no other content

What is KEPT:
    - Real prose ("Now let me read the full Navbar...")
    - Code blocks with content
    - Tool output that has actual text after TOOL: on the same line
      (e.g. "TOOL:Read returned: file contents...")

Exit codes:
    0 = success (or dry-run completed)
    1 = nothing to clean / DB error
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Load env before importing app modules.
env_path = Path(__file__).resolve().parent.parent / ".env.postgres"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

from database_postgres import get_db  # noqa: E402


# Patterns for lines to drop entirely (entire line matches).
_DROP_LINE_RE = re.compile(
    r"^\s*(?:"
    r"PROGRESS:.*"                    # PROGRESS:anything
    r"|TEXT:\s*"                      # TEXT: with nothing after
    r"|\*\*Input:\*\*"               # **Input:**
    r"|\*\*Output:\*\*"              # **Output:**
    r"|```+"                          # stray code fence openers
    r"|```+json\s*"                   # ```json with nothing after
    r"|(?:null|\{\}|\[\]|---)"        # bare telemetry tokens
    r")\s*$",
    re.IGNORECASE,
)

# Matches a single TOOL:<name> token (used to filter space-separated runs).
_TOOL_TOKEN_RE = re.compile(r"^TOOL:[A-Za-z0-9_\-]+$")
_TOOL_PREFIX_RE = re.compile(r"^\s*TOOL:\s*")
_TEXT_PREFIX_RE = re.compile(r"^\s*TEXT:\s*")


def clean_content(content: str) -> tuple[str, bool]:
    """Return (cleaned_content, changed).

    cleaned_content is the input with noise lines removed and prefixes
    stripped. changed is True if any line was dropped or rewritten.
    """
    if not content:
        return content, False

    original_lines = content.split("\n")
    cleaned_lines: list[str] = []
    changed = False

    for line in original_lines:
        # Whole-line drops for PROGRESS:/TEXT:/marker/fence/token lines.
        if _DROP_LINE_RE.match(line):
            changed = True
            continue

        # Handle lines containing one or more TOOL:<name> tokens separated
        # by whitespace (the most common noise pattern — multiple tool calls
        # concatenated on one line: "TOOL:Read TOOL:Read TOOL:Bash").
        # Split on whitespace, drop TOOL: tokens, keep any real text. If
        # nothing survives, drop the whole line.
        stripped = line.strip()
        if stripped and "TOOL:" in stripped:
            tokens = stripped.split()
            survivors = [t for t in tokens if not _TOOL_TOKEN_RE.match(t)]
            if not survivors:
                # Entire line was TOOL: tokens — drop it.
                changed = True
                continue
            # Some real text mixed in (e.g. "TOOL:Read returned: foo").
            # Drop the TOOL: tokens, keep the rest.
            new_line = " ".join(survivors)
            if new_line != line:
                changed = True
            line = new_line

        # Strip TEXT: prefix from otherwise-valid lines.
        if _TEXT_PREFIX_RE.match(line):
            new_line = _TEXT_PREFIX_RE.sub("", line, count=1)
            if new_line != line:
                changed = True
            line = new_line

        # Strip TOOL: prefix from lines that have real content after it.
        if _TOOL_PREFIX_RE.match(line):
            new_line = _TOOL_PREFIX_RE.sub("", line, count=1)
            if new_line != line:
                changed = True
            line = new_line

        # Skip lines that became empty after stripping prefixes.
        if not line.strip():
            continue

        cleaned_lines.append(line)

    # Collapse runs of blank lines (from removed lines) into a single blank.
    result: list[str] = []
    prev_blank = False
    for line in cleaned_lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            changed = True
            continue
        result.append(line)
        prev_blank = is_blank

    # Strip leading/trailing blank lines.
    while result and not result[0].strip():
        result.pop(0)
        changed = True
    while result and not result[-1].strip():
        result.pop()
        changed = True

    cleaned_content = "\n".join(result)
    return cleaned_content, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without modifying the DB")
    parser.add_argument("--session-id", type=int,
                        help="Only clean messages in this session")
    parser.add_argument("--since-days", type=int,
                        help="Only clean messages from the last N days")
    parser.add_argument("--limit", type=int, default=500,
                        help="Max messages to scan (default: 500)")
    args = parser.parse_args()

    where_clauses = ["role = 'assistant'"]
    params: list = []
    if args.session_id is not None:
        where_clauses.append("session_id = %s")
        params.append(args.session_id)
    if args.since_days is not None:
        where_clauses.append("created_at >= NOW() - INTERVAL '%s days'")
        # psycopg doesn't expand %s inside INTERVAL literal cleanly; use a number.
        # Replace the placeholder manually.
        where_clauses[-1] = f"created_at >= NOW() - INTERVAL '{int(args.since_days)} days'"

    # Heuristic: only look at messages that contain TOOL: or PROGRESS: noise.
    # This avoids re-saving clean rows (which would bump updated_at needlessly).
    where_clauses.append("(content LIKE '%%TOOL:%%' OR content LIKE '%%PROGRESS:%%' OR content LIKE '%%TEXT:%%')")
    where_sql = " AND ".join(where_clauses)

    with get_db() as conn:
        cur = conn.execute(
            f"SELECT id, session_id, content FROM messages WHERE {where_sql} "
            f"ORDER BY id DESC LIMIT %s",
            (*params, args.limit),
        )
        rows = cur.fetchall()

    if not rows:
        print("No messages matched the cleanup criteria. Nothing to do.")
        return 0

    print(f"Found {len(rows)} candidate message(s) to scan.")
    print(f"Mode: {'DRY RUN (no DB changes)' if args.dry_run else 'APPLY'}")
    print("-" * 70)

    cleaned_count = 0
    skipped_count = 0
    total_chars_removed = 0

    for row in rows:
        msg_id = row["id"] if isinstance(row, dict) else row[0]
        session_id = row["session_id"] if isinstance(row, dict) else row[1]
        content = row["content"] if isinstance(row, dict) else row[2]
        if not content:
            skipped_count += 1
            continue

        new_content, changed = clean_content(content)
        if not changed:
            skipped_count += 1
            continue
        if not new_content.strip():
            # Don't blank out a message — keep at least a placeholder so the
            # conversation structure (user → assistant turns) is preserved.
            new_content = "(response contained only telemetry — cleaned up)"

        chars_removed = len(content) - len(new_content)
        total_chars_removed += chars_removed
        cleaned_count += 1

        preview_orig = content[:120].replace("\n", " ")
        preview_new = new_content[:120].replace("\n", " ")
        print(f"msg_id={msg_id} session={session_id}")
        print(f"  BEFORE ({len(content)} chars): {preview_orig!r}")
        print(f"  AFTER  ({len(new_content)} chars): {preview_new!r}")
        print(f"  removed {chars_removed} chars")
        print()

        if not args.dry_run:
            with get_db() as conn:
                conn.execute(
                    "UPDATE messages SET content = %s WHERE id = %s",
                    (new_content, msg_id),
                )
                conn.commit()

    print("-" * 70)
    print(f"Summary: {cleaned_count} cleaned, {skipped_count} unchanged, "
          f"{total_chars_removed} chars of noise removed")
    if args.dry_run and cleaned_count > 0:
        print("\nThis was a dry run. Re-run without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
