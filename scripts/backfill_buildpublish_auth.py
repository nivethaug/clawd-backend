#!/usr/bin/env python3
"""Backfill existing projects after the publish-auth hardening.

For every project on this worker:
  1. Ensure projects.secret_key exists (generate + save when NULL).
  2. Ensure DREAMAGENT_PROJECT_SECRET is in the project's .env files
     (backend/.env, telegram/.env, discord/.env, scheduler/.env, root .env).
  3. Patch buildpublish.py (root + backend/) to send X-Project-Secret on
     restart calls — idempotent (skips files already carrying the header).

Run on the WORKER:  cd /root/clawd-backend && ./venv/bin/python scripts/backfill_buildpublish_auth.py
Optional scope:     ... --project 2043
"""
import argparse
import os
import secrets as _secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def _load_env_file() -> None:
    """Parse ../.env ourselves (CRLF-safe, quotes stripped) — setdefault so
    real process env wins. database_postgres.py has no dotenv of its own;
    a bare `python3 scripts/...` shell call has no env either."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        print(f"!! no .env at {env_file} — DB connection will fail")
        return
    for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip().rstrip("\r")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


_load_env_file()

def _from_database_url() -> bool:
    """Derive DB_* from DATABASE_URL (postgres://user:pass@host:port/db)."""
    from urllib.parse import urlparse, unquote
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        return False
    p = urlparse(dsn)
    if p.scheme not in ("postgres", "postgresql"):
        return False
    os.environ.setdefault("DB_USER", unquote(p.username or "admin"))
    os.environ.setdefault("DB_PASSWORD", unquote(p.password or ""))
    os.environ.setdefault("DB_HOST", p.hostname or "localhost")
    os.environ.setdefault("DB_PORT", str(p.port or 5432))
    os.environ.setdefault("DB_NAME", (p.path or "/dreampilot").lstrip("/"))
    return True


def _from_pm2_env() -> bool:
    """The worker's pm2 process carries DB_* in colon format
    (e.g. 'DB_PASSWORD: xxx') — parse it directly."""
    import re
    import subprocess
    try:
        out = subprocess.run(["pm2", "env", os.getenv("BACKFILL_PM2_ID", "76")],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return False
    found = False
    for line in out.splitlines():
        m = re.match(r"^(DB_(?:HOST|PORT|NAME|USER|PASSWORD))\s*[:=]\s*(.+)$", line.strip())
        if m:
            os.environ.setdefault(m.group(1), m.group(2).strip())
            if m.group(1) == "DB_PASSWORD" and m.group(2).strip():
                found = True
    return found


if not os.environ.get("DB_PASSWORD"):
    _from_database_url()
if not os.environ.get("DB_PASSWORD"):
    _from_pm2_env()
if not os.environ.get("DB_PASSWORD"):
    db_keys = []
    ef = BASE_DIR / ".env"
    if ef.exists():
        for raw in ef.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.strip().startswith(("DB_", "DATABASE")) and "=" in raw:
                db_keys.append(raw.split("=")[0].strip())
    pm2_info = "unknown"
    print("!! DB_PASSWORD is still empty — the worker keeps DB config outside .env")
    print(f"   DB-like keys in {ef}: {db_keys or 'NONE'}")
    print("   Likely carried by pm2 env (e.g. DATABASE_URL). Run:")
    print("     pm2 env 76 | grep -iE 'DATABASE|POSTGRES|^DB_'")
    print("   then either export DATABASE_URL=... and rerun this script")
    print("   (it parses DSNs), or export DB_PASSWORD etc. manually.")
    sys.exit(2)

from database_adapter import get_db  # noqa: E402  (after env load)

HEADER_ANCHOR = 'req = _urlreq.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")'
HEADER_BLOCK = (
    "# Auth: the project's own secret scopes this restart to THIS project's\n"
    "            # pm2 app (platform rejects secret-less restarts).\n"
    "            _proj_secret = os.environ.get(\"DREAMAGENT_PROJECT_SECRET\", \"\")\n"
    "            _headers = {\"Content-Type\": \"application/json\"}\n"
    "            if _proj_secret:\n"
    "                _headers[\"X-Project-Secret\"] = _proj_secret\n"
    "            req = _urlreq.Request(endpoint, data=payload, headers=_headers, method=\"POST\")"
)

ENV_CANDIDATES = ["backend/.env", ".env", "telegram/.env", "discord/.env", "scheduler/.env"]
BP_CANDIDATES = ["backend/buildpublish.py", "buildpublish.py"]


def ensure_secret(project_id: int, current) -> str:
    if current:
        return current
    new_secret = _secrets.token_urlsafe(32)
    with get_db() as conn:
        conn.execute("UPDATE projects SET secret_key = %s WHERE id = %s",
                     (new_secret, project_id))
        conn.commit()
    print(f"  secret_key generated for project {project_id}")
    return new_secret


def ensure_env_secret(env_file: Path, secret: str) -> bool:
    if not env_file.exists():
        return False
    content = env_file.read_text(encoding="utf-8", errors="replace")
    if "DREAMAGENT_PROJECT_SECRET" in content:
        return False
    with env_file.open("a", encoding="utf-8") as f:
        f.write(f"\nDREAMAGENT_PROJECT_SECRET={secret}\n")
    return True


def patch_buildpublish(bp_file: Path) -> bool:
    if not bp_file.exists():
        return False
    content = bp_file.read_text(encoding="utf-8", errors="replace")
    if "X-Project-Secret" in content:
        return False  # already patched
    if HEADER_ANCHOR not in content:
        print(f"  !! {bp_file}: restart call anchor not found — patch manually")
        return False
    if "import os" not in content:
        content = "import os\n" + content
    content = content.replace(HEADER_ANCHOR, HEADER_BLOCK)
    bp_file.write_text(content, encoding="utf-8")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=int, default=None, help="single project id")
    ap.add_argument("--root", default="/workspaces", help="workspaces root")
    args = ap.parse_args()

    from database_adapter import get_db

    where = "WHERE project_path IS NOT NULL AND project_path LIKE %s"
    params: tuple = (args.root.rstrip("/") + "/%",)
    if args.project:
        where = "WHERE id = %s"
        params = (args.project,)

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, domain, type_id, secret_key, project_path "
            f"FROM projects {where} ORDER BY id", params).fetchall()

    print(f"projects to process: {len(rows)}")
    patched_bp, env_updated, secrets_generated = 0, 0, 0
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        pid = d["id"]
        ppath = Path(d["project_path"])
        if not ppath.is_dir():
            continue
        print(f"[{pid}] {d.get('name')} -> {ppath}")

        secret = ensure_secret(pid, d.get("secret_key"))
        if not d.get("secret_key"):
            secrets_generated += 1

        for rel in ENV_CANDIDATES:
            if ensure_env_secret(ppath / rel, secret):
                env_updated += 1
                print(f"  + DREAMAGENT_PROJECT_SECRET -> {rel}")

        for rel in BP_CANDIDATES:
            if patch_buildpublish(ppath / rel):
                patched_bp += 1
                print(f"  + patched -> {rel}")

    print(f"\ndone: {len(rows)} projects | secrets generated: {secrets_generated} | "
          f".env updated: {env_updated} | buildpublish patched: {patched_bp}")
    print("next: restart the affected pm2 apps whose backend publish was pending "
          "(or ask the edit chat to retry publish).")


if __name__ == "__main__":
    main()
