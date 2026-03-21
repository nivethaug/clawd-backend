#!/usr/bin/env python3
"""
GLM Read Tool — Custom file reading tool for GLM LLM on Linux.

Exposes a structured tool that GLM can call to read files/dirs,
returns clean text output suitable for LLM consumption.

Usage:
    python glm_read_tool.py                    # interactive demo
    python glm_read_tool.py /path/to/file      # direct read
    python glm_read_tool.py /path/to/dir       # directory listing

Integrate with GLM by passing TOOL_DEFINITION to the API
and calling execute_read_tool() when GLM returns a tool_use block.
"""

import os
import sys
import json
import stat
import subprocess
from pathlib import Path
from typing import Any


# ── Tool definition (pass this to GLM API calls) ─────────────────────────────

# Blocked directories (waste tokens, generated files)
BLOCKED_DIRS = {
    "node_modules", "dist", "build", ".next", ".nuxt", "cache", ".cache",
    "__pycache__", ".git", "vendor", "bower_components", "jspm_packages",
    ".turbo", ".output", ".nuxt", "coverage", ".pytest_cache", "venv", "env"
}

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "read",
        "description": (
            "Read the contents of a file or list a directory on the Linux filesystem. "
            "Handles text files, source code, JSON, CSV (sampled), binary detection, "
            "and directory listings. BLOCKED: node_modules, dist, build, cache, .git, etc. "
            "Always call this before editing or referencing a file you haven't seen yet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file or directory to read."
                },
                "max_lines": {
                    "type": "integer",
                    "description": (
                        "Maximum lines to return for text files. "
                        "Defaults to 200. Use -1 for the full file."
                    ),
                    "default": 200
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based). Default 1.",
                    "default": 1
                }
            },
            "required": ["path"]
        }
    }
}


# ── Core read logic ───────────────────────────────────────────────────────────

MAX_BINARY_SNIFF = 8192   # bytes to check for binary content
MAX_FILE_SIZE    = 1024 * 1024  # 1MB — warn above this


def _is_binary(path: Path) -> bool:
    """Sniff first 8KB for null bytes — reliable binary detector."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(MAX_BINARY_SNIFF)
        return b"\x00" in chunk
    except OSError:
        return False


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_text(path: Path, offset: int, max_lines: int) -> str:
    """Read a text file, respecting offset and max_lines."""
    size = _file_size(path)
    lines_out = []

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, start=1):
            if i < offset:
                continue
            if max_lines != -1 and len(lines_out) >= max_lines:
                break
            # Prefix with line numbers (matches claude-code style)
            lines_out.append(f"{i}\t{line.rstrip()}")

    result = "\n".join(lines_out)

    # Append truncation notice if applicable
    if max_lines != -1 and len(lines_out) >= max_lines:
        total = sum(1 for _ in open(path, encoding="utf-8", errors="replace"))
        if offset + max_lines - 1 < total:
            result += (
                f"\n\n[Showing lines {offset}–{offset + len(lines_out) - 1} "
                f"of {total}. Use offset/max_lines to read more.]"
            )

    if size > MAX_FILE_SIZE:
        result = f"[Warning: large file ({size:,} bytes)]\n" + result

    return result


def _read_csv_sample(path: Path, max_lines: int) -> str:
    """For CSV/TSV: show shape info + first N rows."""
    try:
        import pandas as pd
        nrows = max_lines if max_lines != -1 else None
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
        df = pd.read_csv(path, nrows=nrows, sep=sep)
        total_rows = sum(1 for _ in open(path)) - 1  # subtract header
        header = (
            f"[CSV: {total_rows:,} rows × {len(df.columns)} columns]\n"
            f"Columns: {list(df.columns)}\n\n"
        )
        return header + df.to_string(index=False)
    except ImportError:
        # pandas not available — fall back to plain text read
        return _read_text(path, 1, max_lines)
    except Exception as e:
        return f"[CSV read error: {e}]\n" + _read_text(path, 1, max_lines)


def _read_json_structure(path: Path) -> str:
    """For JSON: show type/keys/length before full content."""
    size = _file_size(path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        if isinstance(data, list):
            header = f"[JSON array: {len(data)} items]\n"
            preview = json.dumps(data[:3], indent=2, ensure_ascii=False)
            suffix = "\n... (truncated)" if len(data) > 3 else ""
            return header + preview + suffix
        elif isinstance(data, dict):
            header = f"[JSON object: {len(data)} keys: {list(data.keys())[:10]}]\n"
            preview = json.dumps(data, indent=2, ensure_ascii=False)
            if size > 8000:
                preview = preview[:8000] + "\n... (truncated)"
            return header + preview
        else:
            return f"[JSON scalar]\n{json.dumps(data)}"
    except json.JSONDecodeError as e:
        return f"[Invalid JSON: {e}]\n" + _read_text(path, 1, 50)


def _list_directory(path: Path) -> str:
    """List directory contents with type indicators and sizes. Filters blocked dirs."""
    try:
        all_entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return f"[Permission denied: {path}]"

    # Filter out blocked directories
    entries = []
    blocked_count = 0
    for entry in all_entries:
        if entry.name in BLOCKED_DIRS:
            blocked_count += 1
            continue
        entries.append(entry)

    lines = [f"Directory: {path.resolve()}", f"{'Name':<40} {'Type':<8} {'Size':>10}",
             "-" * 62]

    for entry in entries:
        try:
            s = entry.stat()
            is_dir = stat.S_ISDIR(s.st_mode)
            size_str = "" if is_dir else f"{s.st_size:,}"
            type_str = "dir" if is_dir else entry.suffix.lstrip(".") or "file"
            name = entry.name + ("/" if is_dir else "")
            lines.append(f"{name:<40} {type_str:<8} {size_str:>10}")
        except OSError:
            lines.append(f"{entry.name:<40} {'?':<8} {'?':>10}")

    summary = f"\n{len(entries)} entries"
    if blocked_count > 0:
        summary += f" ({blocked_count} blocked: node_modules, cache, etc.)"
    lines.append(summary)
    return "\n".join(lines)


def _read_binary_info(path: Path) -> str:
    """For binary files: show file type and hex preview."""
    size = _file_size(path)
    try:
        result = subprocess.run(
            ["file", str(path)], capture_output=True, text=True, timeout=5
        )
        file_type = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        file_type = "unknown binary"

    try:
        result = subprocess.run(
            ["xxd", str(path)], capture_output=True, text=True, timeout=5
        )
        hex_preview = "\n".join(result.stdout.splitlines()[:8])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        with open(path, "rb") as f:
            raw = f.read(64)
        hex_preview = raw.hex(" ")

    return (
        f"[Binary file: {size:,} bytes]\n"
        f"Type: {file_type}\n\n"
        f"Hex preview (first 64 bytes):\n{hex_preview}\n\n"
        f"[Cannot display binary content as text. "
        f"Use a specific tool (e.g. pdf reader, image viewer) for this file type.]"
    )


# ── Main dispatch ─────────────────────────────────────────────────────────────

def _is_blocked_path(p: Path) -> bool:
    """Check if path is inside a blocked directory."""
    for part in p.parts:
        if part in BLOCKED_DIRS:
            return True
    return False


def execute_read_tool(path: str, max_lines: int = 200, offset: int = 1) -> dict[str, Any]:
    """
    Execute the read tool. Called when GLM returns a tool_use block.

    Args:
        path:      File or directory path
        max_lines: Max lines to return (-1 = all)
        offset:    Starting line (1-based)

    Returns:
        {"success": bool, "content": str, "path": str}
    """
    p = Path(path).expanduser()

    # Existence check
    if not p.exists():
        return {
            "success": False,
            "content": f"Error: path does not exist: {p}",
            "path": str(p)
        }

    # Permission check
    if not os.access(p, os.R_OK):
        return {
            "success": False,
            "content": f"Error: permission denied: {p}",
            "path": str(p)
        }

    # Blocked directory check
    if _is_blocked_path(p):
        return {
            "success": False,
            "content": f"Error: blocked directory (saves tokens): {p}",
            "path": str(p)
        }

    try:
        # Directory
        if p.is_dir():
            content = _list_directory(p)

        # Binary file
        elif _is_binary(p):
            content = _read_binary_info(p)

        # CSV / TSV
        elif p.suffix.lower() in (".csv", ".tsv"):
            content = _read_csv_sample(p, max_lines)

        # JSON
        elif p.suffix.lower() == ".json":
            content = _read_json_structure(p)

        # Plain text / source code / everything else
        else:
            content = _read_text(p, offset, max_lines)

        return {"success": True, "content": content, "path": str(p.resolve())}

    except Exception as e:
        return {
            "success": False,
            "content": f"Error reading {p}: {type(e).__name__}: {e}",
            "path": str(p)
        }


# ── GLM integration helper ────────────────────────────────────────────────────

def handle_glm_tool_call(tool_call: dict) -> str:
    """
    Parse a GLM tool_call object and return the tool result as a string.
    Pass the returned string back to GLM as a tool message.

    Example GLM tool_call shape:
        {
            "id": "call_abc123",
            "type": "function",
            "function": {
                "name": "read",
                "arguments": "{\"path\": \"/etc/os-release\"}"
            }
        }
    """
    try:
        name = tool_call["function"]["name"]
        args = json.loads(tool_call["function"]["arguments"])
    except (KeyError, json.JSONDecodeError) as e:
        return f"[Tool parse error: {e}]"

    if name != "read":
        return f"[Unknown tool: {name}]"

    result = execute_read_tool(
        path=args.get("path", ""),
        max_lines=args.get("max_lines", 200),
        offset=args.get("offset", 1),
    )

    if result["success"]:
        return result["content"]
    else:
        return result["content"]  # error message is already human-readable


# ── Example: full GLM conversation loop with read tool ───────────────────────

def run_glm_with_read_tool(user_message: str, api_key: str, model: str = "glm-4-flash"):
    """
    Complete example: send a message to GLM with the read tool available,
    handle tool calls, return final response.

    Requires: pip install zhipuai
    """
    from zhipuai import ZhipuAI

    client = ZhipuAI(api_key=api_key)
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=[TOOL_DEFINITION],
            tool_choice="auto",
        )

        msg = response.choices[0].message

        # No tool call — final answer
        if not msg.tool_calls:
            return msg.content

        # Append assistant message with tool calls
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in msg.tool_calls
            ]
        })

        # Execute each tool call and append results
        for tc in msg.tool_calls:
            tool_result = handle_glm_tool_call({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })

        # Loop back — GLM will now respond with the file content in context


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Interactive demo
        print("GLM Read Tool — interactive mode")
        print("Enter a path to read (or 'q' to quit):\n")
        while True:
            try:
                path = input("path> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if path.lower() in ("q", "quit", "exit"):
                break
            if not path:
                continue
            result = execute_read_tool(path)
            print("\n" + result["content"] + "\n")
    else:
        # Direct read from CLI arg
        path = sys.argv[1]
        max_lines = int(sys.argv[2]) if len(sys.argv) > 2 else 200
        offset = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        result = execute_read_tool(path, max_lines, offset)
        print(result["content"])
        sys.exit(0 if result["success"] else 1)