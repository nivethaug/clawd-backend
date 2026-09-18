#!/usr/bin/env python3
"""Backfill projects.secret_key from each project's backend/.env on the worker.

Fixes projects whose secret was written to backend/.env but never stored in
the projects row (legacy projects created before the cross-VPS proxy auth
feature, or rows where the writer silently failed).

RUN ON THE WORKER VPS (it has both the /workspaces files and DB access via
.env.postgres). Only rows with NULL secret_key are updated — never
overwrites an existing/regenerated secret.

Usage (worker VPS):
    cd /root/clawd-backend
    python3 scripts/backfill_project_secrets.py            # dry-run report
    python3 scripts/backfill_project_secrets.py --apply    # write to DB
"""

import os
import re
import sys
from pathlib import Path

WORKSPACES_ROOT = Path(os.getenv("WORKSPACES_ROOT", "/workspaces"))
ENV_SECRET_KEY = "SECRET_KEY"
APPLY = "--apply" in sys.argv

# workspace dir names look like: 2059_dreamtrace-copy_20260916_171225
PROJECT_ID_RE = re.compile(r"^(\d+)_")


def secret_from_env(env_path: Path) -> str:
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith(f"{ENV_SECRET_KEY}="):
                return line.partition("=")[2].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def main() -> int:
    if not WORKSPACES_ROOT.is_dir():
        print(f"workspaces root not found: {WORKSPACES_ROOT}")
        return 1

    try:
        from database_adapter import get_db
    except ImportError as e:
        print(f"cannot import database_adapter (run from clawd-backend venv): {e}")
        return 1

    env_files = sorted(WORKSPACES_ROOT.glob("user_*/**/backend/.env"))
    print(f"found {len(env_files)} backend .env files under {WORKSPACES_ROOT}")

    scanned = found = fixed = skipped = mismatched = 0
    with get_db() as conn:
        for env_path in env_files:
            m = PROJECT_ID_RE.match(env_path.parent.parent.name)
            if not m:
                continue
            project_id = int(m.group(1))
            scanned += 1
            secret = secret_from_env(env_path.parent, Path(env_path))
            if not secret:
                continue
            row = conn.execute(
                "SELECT secret_key FROM projects WHERE id = %s",
                (project_id,),
            ).fetchone()
            current = (row.get("secret_key") if isinstance(row, dict) else row[0]) if row else None
            if current:
                skipped += 1
                continue
            found += 1
            print(f"  project {project_id}: NULL secret_key -> found in {env_path.parent.name}/backend/.env")
            if APPLY:
                conn.execute(
                    "UPDATE projects SET secret_key = %s WHERE id = %s AND secret_key IS NULL",
                    (secret, project_id),
                )
                fixed += 1
            else:
                mismatched += 1  # dry-run counter

    print(f"\nscanned={scanned} needing_backfill={found} applied={fixed if APPLY else 0} dry_run={not APPLY}")
    if not APPLY and found:
        print("re-run with --apply to write these values to the DB")
    return 0


def secret_from_env(env_dir: Path, env_path: Path) -> str:
    """Read SECRET_KEY from the given .env path (kept separate for clarity)."""
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith(f"{ENV_SECRET_KEY}="):
                return line.partition("=")[2].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


if __name__ == "__main__":
    sys.exit(main())
