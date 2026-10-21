"""
Shared npm invocation helper (Dependency Management Plan, P0).

Every platform-side npm install goes through run_npm() so that:

* The npm DOWNLOAD cache is one explicit shared directory in BOTH
  execution modes (NPM_CONFIG_CACHE, default /srv/cache/npm). Container
  mode already sets this via docker/Dockerfile.user; local mode gets it
  here. Lockfiles and node_modules stay strictly per-project — only the
  downloaded-tarball cache is shared (it is content-addressed by design).
* Every install emits ONE structured log line: command, cwd, cache path,
  duration, exit code, node_modules size delta, and shared-cache usage
  before/after + total. The cache numbers exist to watch for unbounded
  cache growth; if growth is unbounded, the follow-up is an
  `npm cache clean --force` cron or a size cap (decided from this data).

The helper preserves each caller's environment semantics untouched
except for NPM_CONFIG_CACHE (which it forces).
"""
import logging
import os
import shutil
import subprocess
import time
from typing import Optional

NPM_CACHE_DIR = os.getenv("NPM_CONFIG_CACHE", "/srv/cache/npm").strip() or "/srv/cache/npm"
# Resolve the binary once: bare "npm" is not directly executable on Windows.
NPM_BIN = shutil.which("npm") or "npm"

_log = logging.getLogger("dreamagent.npm")


def _du_mb(path: str) -> Optional[float]:
    """Directory size in MB, best-effort (du first, os.walk fallback)."""
    if not path or not os.path.isdir(path):
        return None
    try:
        out = subprocess.run(
            ["du", "-sm", path], capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.split():
            return float(out.stdout.split()[0])
    except Exception:
        pass
    try:
        total = 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total / (1024 * 1024)
    except Exception:
        return None


def run_npm(args, cwd, *, timeout: int = 600, env=None, logger=None, **popen_kwargs):
    """Run `npm <args>` in cwd with the shared cache + structured logging.

    Returns the CompletedProcess (text mode, output captured) so callers
    keep their existing error handling. Extra popen_kwargs (e.g.
    stdout=DEVNULL) are forwarded to subprocess.run.
    """
    log = logger or _log
    env = dict(env) if env is not None else os.environ.copy()
    env["NPM_CONFIG_CACHE"] = NPM_CACHE_DIR
    try:
        os.makedirs(NPM_CACHE_DIR, exist_ok=True)
    except OSError:
        # Cache dir not creatable (permissions/ro fs) — npm falls back to
        # its default cache; the install itself must still proceed.
        pass

    nm_path = os.path.join(cwd, "node_modules")
    nm_before = _du_mb(nm_path) or 0.0
    cache_before = _du_mb(NPM_CACHE_DIR)

    cmd = [NPM_BIN, *args]
    run_kwargs = {"capture_output": True, "text": True}
    run_kwargs.update(popen_kwargs)
    if "stdout" in run_kwargs or "stderr" in run_kwargs:
        run_kwargs.pop("capture_output", None)
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), env=env, timeout=timeout, **run_kwargs)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        log.error(
            "[NPM] cmd=%s cwd=%s cache=%s duration=%.1fs exit=TIMEOUT(%ds)",
            " ".join(cmd), cwd, NPM_CACHE_DIR, time.time() - t0, timeout)
        raise

    elapsed = time.time() - t0
    nm_after = _du_mb(nm_path) or 0.0
    cache_after = _du_mb(NPM_CACHE_DIR)
    if cache_before is not None and cache_after is not None:
        cache_delta = f"{cache_after - cache_before:+.1f}MB"
        cache_total = f"{cache_after:.1f}MB"
    else:
        cache_delta = "n/a"
        cache_total = "n/a"
    log.info(
        "[NPM] cmd=%s cwd=%s cache=%s duration=%.1fs exit=%d "
        "node_modules_delta=%+.1fMB cache_delta=%s cache_total=%s",
        " ".join(cmd), cwd, NPM_CACHE_DIR, elapsed, rc,
        nm_after - nm_before, cache_delta, cache_total)
    return proc
