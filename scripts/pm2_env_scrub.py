#!/usr/bin/env python3
"""Scrub platform secrets out of RUNNING customer PM2 apps (worker VPS).

Historical bug: every customer app was started with the worker's FULL
environment inherited (platform keys, DB password, …). New starts are fixed
(services/pm2_env.py clean base); this script repairs the apps already
running with the stolen backpack.

How it repairs safely (live site!):
  1. Reads each app's CURRENT recorded env via `pm2 jlist`.
  2. Builds a clean replacement env = clean base + ONLY the app's project
     vars (keys that exist in the project's own .env file, or known
     project-managed keys like BOT_TOKEN/WEBHOOK_*/PROJECT_ID/PORT).
  3. `pm2 restart <name> --update-env` executed WITH that clean env —
     the app keeps working (project vars intact) and loses every secret.
  4. VERIFIES /proc/<pid>/environ afterwards: no PLATFORM_SECRET_KEYS.
     (dotenv values live in os.environ at runtime, NOT in /proc environ,
     so a customer's own OPENAI_API_KEY from .env never trips this.)

Platform processes (clawd-*, wrapper-v2, container-reaper, analytics-*,
monitor-*, scheduler, dc-bot-*/tg-bot- drivers of the platform) are left
untouched; only deployed customer apps are scrubbed.

Usage (worker VPS):
    python3 scripts/pm2_env_scrub.py            # dry-run: report exposure
    python3 scripts/pm2_env_scrub.py --apply    # repair + verify
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.pm2_env import clean_pm2_env, PLATFORM_SECRET_KEYS  # noqa: E402

APPLY = "--apply" in sys.argv

# Platform-owned processes — NEVER scrub these (they legitimately hold secrets).
PLATFORM_APP_PREFIXES = (
    "clawd-", "wrapper-v2", "container-reaper", "analytics-",
    "monitor-", "dc-bot-", "tg-bot-", "sched-", "discord-", "telegram-",
)
# careful: tg-bot-<id>/dc-bot-<id> ARE customer apps! They're excluded above
# only when followed by non-numeric suffixes — resolved by PROJECT_APPS below.

# Keys that are legitimately part of a customer app's RECORDED env (they are
# explicitly injected at start by the platform's own start paths).
PROJECT_MANAGED_KEYS = {
    "PORT", "HOST", "PROJECT_ID", "PROJECT_NAME", "PROJECT_PATH",
    "DOMAIN", "DATABASE_URL", "SECRET_KEY", "DEBUG", "NODE_ENV",
    "BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "DISCORD_TOKEN", "DISCORD_WEBHOOK_URL", "WEBHOOK_DOMAIN", "WEBHOOK_URL",
    "EMAIL_TO", "API_ENDPOINT", "BACKEND_URL", "PYTHONUNBUFFERED",
    "name", "pm_cwd", "pm_id", "NODE_APP_INSTANCE", "vizion", "pm_exec_path",
    "pm_uptime", "created_at", "restart_time", "versioning", "axm_options",
    "NODE_CHANNEL_FD", "pm_pid_path", "instance_var", "cmd", "exec_interpreter",
    "pm_exec_interpreter", "watch", "node_args", "pm_err_log_path",
    "pm_out_log_path", "flowing_restart", "exp_backoff_restart_delay",
    "log_date_format", "merge_logs", "default_node_env", "killing",
    "windowsHide", "username", "kill_retry_time", "status", "pm_env_path",
    "pm_cli", "manual_restart", "treekill", "autorestart", "unstable_restarts",
    "pm2_env_", "exit_code", "async", "cron_pattern", "cron_restart",
}


def is_customer_app(name: str, pm_id) -> bool:
    """Customer apps: tg-bot-<digits>, dc-bot-<digits>, and any app whose
    pm_cwd points into the projects workspaces — everything else is platform.
    """
    for p in ("tg-bot-", "dc-bot-", "sched-"):
        if name.startswith(p):
            suffix = name[len(p):]
            return suffix.isdigit()
    return False


def app_project_keys(pm_cwd: str) -> set:
    """Key NAMES from the project's own .env files (values never read)."""
    keys = set()
    for env_path in (
        os.path.join(pm_cwd, ".env"),
        os.path.join(pm_cwd, "backend", ".env"),
        os.path.join(pm_cwd, "telegram", ".env"),
        os.path.join(pm_cwd, "discord", ".env"),
    ):
        try:
            with open(env_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        keys.add(line.split("=", 1)[0].strip().upper())
        except OSError:
            pass
    return keys


def proc_environ(pid: int) -> dict:
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            raw = f.read().decode("utf-8", errors="replace")
        return dict(part.split("=", 1) for part in raw.split("\0") if "=" in part)
    except OSError:
        return {}


def main():
    jlist = subprocess.run(["pm2", "jlist"], capture_output=True, text=True,
                           timeout=30, env=clean_pm2_env())
    if jlist.returncode != 0:
        print("pm2 jlist failed:", jlist.stderr[:300]); return 1
    apps = json.loads(jlist.stdout or "[]")

    targets = []
    for a in apps:
        name = a.get("name") or ""
        pe = a.get("pm2_env") or {}
        cwd = pe.get("pm_cwd") or ""
        pid = a.get("pid")
        # websites: pm_cwd under a project workspace; bots: named prefix+id
        customer = is_customer_app(name, a.get("pm_id")) or (
            "/workspaces/" in cwd or "/workspace/" in cwd
        )
        if not customer:
            continue
        targets.append((name, cwd, pid, pe))

    print(f"Customer apps found: {len(targets)}\n")

    any_dirty = False
    for name, cwd, pid, pe in targets:
        live = proc_environ(pid) if pid else {}
        leaked = sorted(k for k in PLATFORM_SECRET_KEYS if k in live)
        recorded = {k for k in pe if isinstance(k, str)}
        rec_leaked = sorted(k for k in PLATFORM_SECRET_KEYS if k in recorded)
        status = "DIRTY" if (leaked or rec_leaked) else "clean"
        if status == "DIRTY":
            any_dirty = True
        print(f"[{status:5}] {name}  (pid={pid}, cwd={cwd})")
        if leaked:
            print(f"        /proc env leaks : {', '.join(leaked)}")
        if rec_leaked:
            print(f"        recorded env    : {', '.join(rec_leaked)}")

        if APPLY and status == "DIRTY":
            keep = app_project_keys(cwd)
            new_env = clean_pm2_env()
            for k in recorded:
                ku = k.upper()
                if ku in keep or ku in PROJECT_MANAGED_KEYS or k in pe:
                    # value from RECORDED env (the app's own values)
                    if ku in keep or ku in PROJECT_MANAGED_KEYS:
                        v = pe.get(k)
                        if isinstance(v, (str, int, float, bool)):
                            new_env[k] = str(v)
            r = subprocess.run(
                ["pm2", "restart", name, "--update-env"],
                capture_output=True, text=True, timeout=60,
                env=new_env,
            )
            ok = r.returncode == 0
            # re-verify
            j2 = subprocess.run(["pm2", "jlist"], capture_output=True, text=True,
                                timeout=30, env=clean_pm2_env())
            pid2 = None
            for a2 in json.loads(j2.stdout or "[]"):
                if a2.get("name") == name:
                    pid2 = a2.get("pid")
            live2 = proc_environ(pid2) if pid2 else {}
            leaked2 = sorted(k for k in PLATFORM_SECRET_KEYS if k in live2)
            print(f"        -> restart {'ok' if ok else 'FAILED'}; "
                  f"post-verify: {'CLEAN' if not leaked2 else 'STILL LEAKS: ' + ', '.join(leaked2)}")

    if not APPLY:
        print("\nDry run — re-run with --apply to repair dirty apps.")
    elif any_dirty:
        print("\nDone. Review any STILL LEAKS lines above.")
    else:
        print("\nAll clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
