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

WORKSPACES_ROOT = Path(os.getenv("WORKSPACES_ROOT", "/workspaces"))
CONTAINER_PREFIX = "dreamagent-user-"
APPLY = "--apply" in sys.argv


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
    from database_adapter import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE id = %s", (user_id,)
        ).fetchone()
    return row is not None


def delete_container_row(user_id: int) -> None:
    from database_adapter import get_db
    with get_db() as conn:
        conn.execute("DELETE FROM user_containers WHERE user_id = %s", (user_id,))
        conn.commit()


def main():
    if os.geteuid() != 0:
        print("note: not root — docker perms / workspace rmtree may fail\n")

    containers = list_user_containers()
    if not containers:
        print("No dreamagent-user-* containers found. Nothing to do.")
        return

    print(f"Found {len(containers)} per-user container(s).\n")
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
