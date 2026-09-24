#!/usr/bin/env python3
"""Find and (optionally) delete GitHub repos that no longer belong to any
live DreamAgent project.

Background: project deletion removes the DB row first; when the GitHub step
fails (as it did while `delete_repository` was missing on the worker), the
repo is orphaned forever. This script reconciles GitHub -> live projects and
deletes orphans directly via the `gh` CLI (bypassing GitHubService).

Usage (on the worker VPS, where `gh` is authenticated and the DB env vars
live in /root/clawd-backend/.env):

    venv/bin/python scripts/cleanup_orphan_repos.py             # DRY RUN — table only
    venv/bin/python scripts/cleanup_orphan_repos.py --delete    # actually delete orphans
    venv/bin/python scripts/cleanup_orphan_repos.py --exclude repo-a repo-b

Safety:
  - Dry-run by default; nothing is deleted without --delete.
  - Platform/infrastructure repos are hard-protected (never touched):
    exact names below, plus any repo whose name contains clawd/wrapper/
    muse/dreamagent.
  - A repo is KEPT if ANY live project references it via repo_url, domain,
    or project-name slug.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Exact infra repos + substring guards. Over-protecting is fine; these can
# never be project repos.
PROTECTED_EXACT = {"clawd-backend", "wrapper-v2", "muse-companion-app"}
PROTECTED_SUBSTRINGS = ("clawd", "wrapper", "muse", "dreamagent")


def run_gh(args, timeout=60):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def slugify(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    return s.strip("-")


def repo_name_from_url(url: str) -> str:
    return (url or "").rstrip("/").split("/")[-1].replace(".git", "").strip().lower()


def load_live_projects() -> dict:
    """repo_name (lower) -> human-readable reason it must be kept."""
    from dotenv import load_dotenv
    # Try the usual suspects; the worker's DB env may live only in the
    # PM2 environment (ecosystem file), not in a repo .env.
    for env_path in (REPO_ROOT / ".env", Path.cwd() / ".env", Path("/root/.env")):
        if env_path.exists():
            load_dotenv(env_path)

    if not os.getenv("DB_HOST") or not os.getenv("DB_PASSWORD"):
        print("ERROR: DB_HOST / DB_PASSWORD not found in any .env — the worker\n"
              "likely gets them from its PM2 environment. Re-run like this:\n"
              "\n"
              "  export $(pm2 env 76 | grep -E '^DB_' | xargs) \\\n"
              "    && venv/bin/python scripts/cleanup_orphan_repos.py\n")
        sys.exit(2)

    from database_postgres import get_db

    wanted = {}
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, domain, repo_url FROM projects"
        ).fetchall()

    for _row in rows:
        row = dict(_row)  # rows may be DictRow-like; normalise
        pid = row.get("id")
        pairs = []
        if row.get("repo_url"):
            pairs.append((repo_name_from_url(row["repo_url"]), f"repo_url of project {pid}"))
        if row.get("domain"):
            pairs.append((row["domain"].strip().lower(), f"domain of project {pid}"))
        if row.get("name"):
            pairs.append((slugify(row["name"]), f"name of project {pid}"))
        for repo, why in pairs:
            if repo:
                wanted.setdefault(repo, why)
    return wanted


def load_github_repos() -> list:
    out = run_gh(["repo", "list", "--limit", "500",
                  "--json", "nameWithOwner,name,isPrivate,updatedAt,pushedAt"])
    repos = json.loads(out or "[]")
    for r in repos:
        pushed = r.get("pushedAt") or r.get("updatedAt") or ""
        try:
            dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            r["_age_days"] = (datetime.now(timezone.utc) - dt).days
        except Exception:
            r["_age_days"] = -1
    return repos


def is_protected(name: str) -> bool:
    n = name.lower()
    return n in PROTECTED_EXACT or any(s in n for s in PROTECTED_SUBSTRINGS)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delete", action="store_true",
                    help="Actually delete orphan repos (default: dry run)")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="Extra repo names to protect from deletion")
    args = ap.parse_args()

    print("Loading live projects from DB ...")
    wanted = load_live_projects()
    print(f"  {len(wanted)} repo names referenced by live projects")

    print("Listing GitHub repos ...")
    repos = load_github_repos()
    owner = repos[0]["nameWithOwner"].split("/")[0] if repos else "unknown"
    print(f"  {len(repos)} repos under {owner}\n")

    extra_protected = {e.lower() for e in args.exclude}
    keep, protected, orphans = [], [], []

    for r in sorted(repos, key=lambda x: x["name"]):
        name = r["name"]
        key = name.lower()
        if is_protected(name) or key in extra_protected:
            protected.append(r)
        elif key in wanted:
            keep.append((r, wanted[key]))
        else:
            orphans.append(r)

    def show(r, note=""):
        priv = "private" if r.get("isPrivate") else "PUBLIC"
        age = f"{r['_age_days']}d" if r["_age_days"] >= 0 else "?"
        print(f"  {r['nameWithOwner']:<45} {priv:<7} pushed {age:>5}  {note}")

    print(f"=== KEEP — referenced by a live project ({len(keep)}) ===")
    for r, why in keep:
        show(r, why)

    print(f"\n=== PROTECTED — platform/infra ({len(protected)}) ===")
    for r in protected:
        show(r)

    print(f"\n=== ORPHAN CANDIDATES — no live project references them ({len(orphans)}) ===")
    for r in orphans:
        show(r)

    if not orphans:
        print("\nNo orphans found. Nothing to do.")
        return

    if not args.delete:
        print(f"\nDRY RUN — {len(orphans)} orphans would be deleted.")
        print("Re-run with --delete to remove them:")
        print(f"  venv/bin/python scripts/cleanup_orphan_repos.py --delete")
        return

    print(f"\nDeleting {len(orphans)} orphan repos ...")
    ok = fail = 0
    for r in orphans:
        try:
            run_gh(["repo", "delete", r["nameWithOwner"], "--yes"], timeout=120)
            print(f"  ✓ deleted {r['nameWithOwner']}")
            ok += 1
        except Exception as e:
            print(f"  ✗ FAILED {r['nameWithOwner']}: {e}")
            fail += 1
    print(f"\nDone: {ok} deleted, {fail} failed.")


if __name__ == "__main__":
    main()
