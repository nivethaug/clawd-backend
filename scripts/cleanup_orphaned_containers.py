#!/usr/bin/env python3
"""Remove Docker containers left behind by already-deleted users (worker VPS).

Users deleted BEFORE the container-cleanup fix left their per-user container
(dreamagent-user-<id>) running on the worker even though the user, projects,
and workspace were gone. This script finds those orphans and removes them.

A container is ORPHANED when either:
  - its workspace dir (/workspaces/user_<id>) no longer exists, OR
  - the user id has no row in the users table (user was deleted from the DB)
Non-orphans (live user + workspace present) are never touched.

Also cleans stale user_containers registry rows for removed containers.

RUN ON THE WORKER VPS (docker + DB access via database_adapter env).

Usage (worker VPS):
    cd /root/clawd-backend
    python3 scripts/cleanup_orphaned_containers.py            # dry-run report
    python3 scripts/cleanup_orphaned_containers.py --apply    # actually remove
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Running as scripts/xxx.py puts scripts/ on sys.path, not the repo root —
# add it so `database_adapter` (and its env-based DB config) is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WORKSPACES_ROOT = Path(os.getenv("WORKSPACES_ROOT", "/workspaces"))
CONTAINER_PREFIX = "dreamagent-user-"
APPLY = "--apply" in sys.argv

# ---------------------------------------------------------------------------
# DB access: prefer database_adapter (needs the backend venv — it requires
# psycopg2). Fall back to the psql CLI using the same DB_* config the app
# uses (exported env vars, or the .env.postgres file in the repo root).
# ---------------------------------------------------------------------------

_db_cfg = None
_db_mode = None


def _load_db_config():
    """Resolve DB_* settings: process env first, then .env.postgres file."""
    global _db_cfg, _db_mode
    if _db_cfg is not None:
        return _db_cfg
    cfg = {k: os.getenv(k, "") for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")}
    env_file = Path(__file__).resolve().parent.parent / ".env.postgres"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k in cfg and not cfg[k]:
                    cfg[k] = v
    if not all(cfg.values()):
        raise RuntimeError(
            f"incomplete DB config (need DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD "
            f"from env or {env_file})"
        )
    _db_cfg = cfg
    return cfg


def _run_psql(sql: str) -> str:
    cfg = _load_db_config()
    env = os.environ.copy()
    env["PGPASSWORD"] = cfg["DB_PASSWORD"]
    r = subprocess.run(
        ["psql", "-h", cfg["DB_HOST"], "-p", cfg["DB_PORT"],
         "-U", cfg["DB_USER"], "-d", cfg["DB_NAME"], "-tAc", sql],
        capture_output=True, text=True, timeout=30, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout.strip()


def _db_user_exists(user_id: int) -> bool:
    """True iff the users table still has this id."""
    global _db_mode
    try:
        from database_adapter import get_db  # noqa: F401 — needs backend venv
        _db_mode = "database_adapter"
        with get_db() as conn:
            row = conn.execute("SELECT 1 FROM users WHERE id = %s", (user_id,)).fetchone()
        return row is not None
    except ImportError:
        _db_mode = "psql"
        return _run_psql(f"SELECT 1 FROM users WHERE id = {int(user_id)}") == "1"


def _db_delete_container_row(user_id: int) -> None:
    try:
        from database_adapter import get_db
        with get_db() as conn:
            conn.execute("DELETE FROM user_containers WHERE user_id = %s", (user_id,))
            conn.commit()
    except ImportError:
        _run_psql(f"DELETE FROM user_containers WHERE user_id = {int(user_id)}")


def list_user_containers():
    """All dreamagent-user-* containers (running + stopped) -> {user_id: name}."""
    r = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={CONTAINER_PREFIX}",
         "--format", "{{.Names}}\t{{.Status}}"],
        capture_output=True, text=True, timeout=30,
    )
    containers = {}
    for line in r.stdout.strip().splitlines():
        if not line:
            continue
        name, _, status = line.partition("\t")
        if not name.startswith(CONTAINER_PREFIX):
            continue
        suffix = name[len(CONTAINER_PREFIX):]
        if not suffix.isdigit():
            continue  # not a per-user container — never touch
        containers[int(suffix)] = (name, status)
    return containers


def user_exists(user_id: int) -> bool:
    return _db_user_exists(user_id)


def delete_container_row(user_id: int) -> None:
    _db_delete_container_row(user_id)


def main():
    if os.geteuid() != 0:
        print("note: not root — docker perms / workspace rmtree may fail\n")

    containers = list_user_containers()
    if not containers:
        print("No dreamagent-user-* containers found. Nothing to do.")
        return

    print(f"Found {len(containers)} per-user container(s).")
    try:
        _load_db_config()
        try:
            import database_adapter  # noqa: F401
            _mode = "database_adapter"
        except ImportError:
            _mode = "psql fallback"
        print(f"(db access: {_mode})\n")
    except Exception as exc:
        print(f"\nDB config incomplete: {exc}")
        return
    orphans = []
    for user_id, (name, status) in sorted(containers.items()):
        ws = WORKSPACES_ROOT / f"user_{user_id}"
        ws_ok = ws.is_dir()
        try:
            u_ok = user_exists(user_id)
        except Exception as exc:
            print(f"  SKIP user_{user_id}: DB lookup failed ({exc})")
            continue

        reasons = []
        if not ws_ok:
            reasons.append("workspace missing")
        if not u_ok:
            reasons.append("user not in DB")

        if reasons:
            orphans.append((user_id, name, status, ws_ok, reasons))
            print(f"  ORPHAN  {name}  ({status})  -> {'; '.join(reasons)}")
        else:
            print(f"  keep    {name}  ({status})  (live user + workspace)")

    if not orphans:
        print("\nNo orphans. Nothing to do.")
        return

    print(f"\n{len(orphans)} orphaned container(s) found.")
    if not APPLY:
        print("Dry run — re-run with --apply to remove them:")
        for user_id, name, _, _, _ in orphans:
            print(f"  docker rm -f {name}")
        return

    print("Applying...\n")
    for user_id, name, _, ws_ok, _ in orphans:
        r = subprocess.run(["docker", "rm", "-f", name],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            print(f"  removed container {name}")
        else:
            print(f"  FAILED to remove {name}: {r.stderr.strip()}")
            continue

        ws = WORKSPACES_ROOT / f"user_{user_id}"
        if ws.is_dir():
            shutil.rmtree(ws, ignore_errors=True)
            print(f"  removed workspace  {ws}")

        try:
            delete_container_row(user_id)
        except Exception as exc:
            print(f"  warn: could not delete user_containers row for {user_id}: {exc}")

    print("\nDone.")


if __name__ == "__main__":
    main()
