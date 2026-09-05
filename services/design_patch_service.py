"""
Design patch service — Path A (agentless visual edits).

Applies style/text patches to project source files, commits them as
"Design: <label>" entries in the existing commit_log, and exposes a
coalesced fast rebuild (vite-only, atomic dist swap so a failed build
never takes the live site down).
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Dict, Optional

from database_postgres import get_db
from services.design_source_map import resolve_node_file
from services.design_tailwind_patch import (
    PatchError,
    apply_style_intent,
    apply_text_change,
)

logger = logging.getLogger(__name__)

MAX_PATCH_BYTES = 64 * 1024  # diff cap per patch
_ALLOWED_PREFIXES = ("src/", "index.html")  # relative to frontend/


class DesignPatchError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _frontend_path(project_path: str) -> Path:
    fe = Path(project_path) / "frontend"
    if not fe.is_dir():
        raise DesignPatchError("Project has no frontend directory", 404)
    return fe


def apply_design_patch(project_id: int, project_path: str, payload: dict) -> dict:
    """Apply a single visual patch. Raises DesignPatchError on any refusal."""
    node = payload.get("node") or {}
    label = (payload.get("label") or "Visual edit").strip()[:120]
    intent = payload.get("style_intent") or {}
    text_change = payload.get("text_change")

    if not intent and not text_change:
        raise DesignPatchError("Nothing to apply (no style_intent or text_change)")
    if len(str(payload)) > MAX_PATCH_BYTES:
        raise DesignPatchError("Patch payload too large", 413)

    fe = _frontend_path(project_path)
    match = resolve_node_file(fe, node)
    if not match:
        raise DesignPatchError(
            "Can't lock this node in code. AI will interpret.", 422
        )

    rel = match.file
    # Path safety: the relative file comes from page attributes (data-da-source)
    # and must stay inside frontend/. Backslashes / '..' / absolute paths are
    # rejected, and the resolved real path must remain under frontend/.
    rel_parts = PurePosixPath(rel).parts
    if (
        not rel.startswith(_ALLOWED_PREFIXES)
        or "\\" in rel
        or ".." in rel_parts
        or rel_parts and rel_parts[0] == "/"
    ):
        raise DesignPatchError(f"File outside editable scope: {rel}", 403)

    target = fe / rel
    try:
        fe_real = os.path.realpath(fe)
        target_real = os.path.realpath(target)
        if not target_real.startswith(fe_real + os.sep):
            raise DesignPatchError(f"File outside editable scope: {rel}", 403)
    except DesignPatchError:
        raise
    except Exception as e:
        raise DesignPatchError(f"Cannot resolve {rel}: {e}", 400)
    try:
        content = target.read_text(encoding="utf-8")
    except OSError as e:
        raise DesignPatchError(f"Cannot read {rel}: {e}", 500)

    try:
        if text_change:
            new_content = apply_text_change(
                content, text_change.get("before", ""), text_change.get("after", "")
            )
            detail = f'text "{text_change.get("before", "")[:30]}" → "{text_change.get("after", "")[:30]}"'
        else:
            # Target the literal class string found in the file — the node's
            # runtime className can differ (cn() merges, ordering), in which
            # case the mapper already resolved the real in-file attribute.
            result = apply_style_intent(
                content,
                match.class_in_file or node.get("className"),
                node.get("textPreview"),
                intent,
            )
            new_content = result.new_content
            detail = result.utility or "style"
    except PatchError as e:
        raise DesignPatchError(str(e), 422)

    if new_content == content:
        raise DesignPatchError("No effective change", 422)
    if abs(len(new_content) - len(content)) > MAX_PATCH_BYTES:
        raise DesignPatchError("Resulting diff too large", 413)

    target.write_text(new_content, encoding="utf-8")

    commit_hash, log_id = _commit_design_change(
        project_id, Path(project_path), rel, f"Design: {label}"
    )
    logger.info(
        "[DESIGN] project=%s file=%s %s commit=%s", project_id, rel, detail, commit_hash
    )
    return {
        "success": True,
        "file": rel,
        "commit_id": commit_hash,
        "log_id": log_id,
        "detail": detail,
        "confidence": match.confidence,
    }


def _commit_design_change(
    project_id: int, project_root: Path, rel_file: str, message: str
) -> tuple[Optional[str], Optional[int]]:
    """git add + commit the patched file; record in commit_log."""
    commit_hash = None
    try:
        env = dict(os.environ, GIT_AUTHOR_NAME="DreamAgent Design",
                   GIT_COMMITTER_NAME="DreamAgent Design",
                   GIT_AUTHOR_EMAIL="design@dreamagent.cloud",
                   GIT_COMMITTER_EMAIL="design@dreamagent.cloud")
        subprocess.run(
            ["git", "add", str(Path("frontend") / rel_file)],
            cwd=str(project_root), capture_output=True, timeout=30, env=env,
        )
        res = subprocess.run(
            ["git", "commit", "-m", message, "--no-verify"],
            cwd=str(project_root), capture_output=True, text=True, timeout=60, env=env,
        )
        if res.returncode == 0:
            h = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(project_root), capture_output=True, text=True, timeout=30,
            )
            commit_hash = h.stdout.strip() or None
        else:
            logger.warning("[DESIGN] git commit failed: %s", (res.stderr or "")[:200])
    except Exception as e:  # non-fatal — file is already patched
        logger.warning("[DESIGN] git error: %s", e)

    log_id = None
    try:
        with get_db() as conn:
            cur = conn.execute(
                # native %s placeholders — the CursorAsConnection wrapper only
                # translates '?', and any literal '%' in the SQL breaks
                # psycopg2's parameter formatting.
                """INSERT INTO commit_log
                   (project_id, session_id, message_id, commit_hash, commit_message, status)
                   VALUES (%s, NULL, NULL, %s, %s, 'committed') RETURNING id""",
                (project_id, commit_hash or "uncommitted", message),
            )
            row = cur.fetchone()
            if row is not None:
                log_id = row["id"] if isinstance(row, dict) else row[0]
    except Exception as e:  # non-fatal — file is already patched
        logger.warning("[DESIGN] commit_log insert failed: %s", e)

    return commit_hash, log_id


def list_design_commits(project_id: int, limit: int = 20) -> list:
    with get_db() as conn:
        rows = conn.execute(
            # LIKE pattern passed as a PARAMETER — a literal '%' in the SQL
            # string is misread by psycopg2 as a format placeholder.
            """SELECT id, commit_hash, commit_message, status, created_at
               FROM commit_log
               WHERE project_id = %s AND commit_message LIKE %s
                 AND status != 'reverted'
               ORDER BY created_at DESC, id DESC LIMIT %s""",
            (project_id, "Design: %", max(1, min(limit, 50))),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["label"] = d.pop("commit_message", "").removeprefix("Design: ")
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Fast build — coalesced per project, atomic dist swap
# ---------------------------------------------------------------------------

_design_build_locks: Dict[int, asyncio.Lock] = {}
_design_build_pending: set = set()


def _get_build_lock(project_id: int) -> asyncio.Lock:
    if project_id not in _design_build_locks:
        _design_build_locks[project_id] = asyncio.Lock()
    return _design_build_locks[project_id]


async def run_design_build(project_path: str, project_id: int) -> dict:
    """Vite-only rebuild into dist-da + atomic swap. Coalesces concurrent
    callers: while one build runs, later callers wait and (at most) one
    trailing rebuild runs to pick up edits made during the build."""
    lock = _get_build_lock(project_id)
    started = time.time()
    async with lock:
        first = await _fast_build_once(project_path)
        # if edits landed while we were building, run one more pass
        while project_id in _design_build_pending:
            _design_build_pending.discard(project_id)
            first = await _fast_build_once(project_path)
    first["build_time"] = round(time.time() - started, 1)
    first["coalesced"] = True
    return first


def mark_design_build_pending(project_id: int) -> None:
    """Called when a patch lands while a build is already running."""
    _design_build_pending.add(project_id)


async def _fast_build_once(project_path: str) -> dict:
    fe = _frontend_path(project_path)
    if not (fe / "package.json").is_file():
        return {"success": False, "error": "No package.json in frontend/"}

    env = dict(os.environ)
    env["NODE_ENV"] = "development"

    cmd = ["npm", "run", "build", "--", "--outDir", "dist-da", "--emptyOutDir"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(fe),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=420)
    except FileNotFoundError:
        return {"success": False, "error": "npm not found on worker"}
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {"success": False, "error": "Build timed out (7 min)"}

    text = (out or b"").decode("utf-8", errors="ignore")
    if proc.returncode != 0 or not (fe / "dist-da" / "index.html").is_file():
        # failed build never touches the live dist/
        import shutil

        shutil.rmtree(fe / "dist-da", ignore_errors=True)
        return {"success": False, "error": text[-600:] or "build failed"}

    # atomic-ish swap: dist -> dist-old, dist-da -> dist
    import shutil

    dist, old, new = fe / "dist", fe / "dist-old", fe / "dist-da"
    shutil.rmtree(old, ignore_errors=True)
    if dist.exists():
        os.rename(dist, old)
    try:
        os.rename(new, dist)
    except OSError:
        if old.exists():
            os.rename(old, dist)  # restore
        return {"success": False, "error": "dist swap failed"}
    shutil.rmtree(old, ignore_errors=True)
    return {"success": True, "output": text[-300:]}
