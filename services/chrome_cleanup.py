"""
Chrome DevTools cleanup utilities.

Shared logic for reaping chrome-devtools-mcp processes and leftover browser
tabs after a Claude session. Used by:
  - acp_chat_handler.py     (chat / edit sessions)
  - acp_frontend_editor_v2  (website CREATE sessions)

WHY THIS EXISTS
---------------
The chrome-devtools MCP opens browser tabs on the persistent Chrome instance
(systemd `chrome-devtools.service` on :9222, forwarded to :9223 for containers).
When a Claude session ends, the MCP server may exit without closing its tabs,
leaving renderer processes (~130MB each) that accumulate and starve the worker
of RAM. This module:
  1. Kills any chrome-devtools-mcp processes (inside the container if container
     mode, else on host).
  2. Closes leftover browser tabs via the CDP HTTP API, keeping the seed
     about:blank so Chrome doesn't exit.

Both functions are safe to call repeatedly and no-op on any failure.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import time
import urllib.request
from typing import Optional, Set

logger = logging.getLogger("chrome_cleanup")


def _resolve_container_name(user_id: Optional[int]) -> Optional[str]:
    """Resolve the per-user container name if running in container mode.

    Returns None in local mode (no container), so callers fall back to
    host-side pgrep/kill.
    """
    if os.getenv("EXECUTION_MODE", "").lower() != "container":
        return None
    if not user_id or not isinstance(user_id, int) or user_id <= 0:
        return None
    return f"dreamagent-user-{user_id}"


def _get_chrome_devtools_pids(user_id: Optional[int] = None) -> Set[int]:
    """Find chrome-devtools-mcp PIDs (inside the container in container mode)."""
    container_name = _resolve_container_name(user_id)
    if container_name:
        try:
            result = subprocess.run(
                ["docker", "exec", container_name, "pgrep", "-f", "chrome-devtools-mcp"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = {int(p) for p in result.stdout.split() if p.isdigit()}
                if pids:
                    logger.info(f"[CHROME-CLEANUP] Found chrome-devtools-mcp PIDs in {container_name}: {pids}")
                return pids
            return set()
        except Exception as e:
            logger.warning(f"[CHROME-CLEANUP] Error getting PIDs from {container_name}: {e}")
            return set()

    # Local mode — query on the host.
    try:
        result = subprocess.check_output(
            ["pgrep", "-f", "chrome-devtools-mcp"], stderr=subprocess.DEVNULL
        ).decode().strip()
        pids = {int(p) for p in result.split() if p}
        if pids:
            logger.info(f"[CHROME-CLEANUP] Found chrome-devtools-mcp PIDs on host: {pids}")
        return pids
    except subprocess.CalledProcessError:
        return set()
    except Exception as e:
        logger.warning(f"[CHROME-CLEANUP] Error getting host PIDs: {e}")
        return set()


def _kill_pids(pids: Set[int], user_id: Optional[int] = None) -> None:
    """SIGTERM then SIGKILL the given PIDs (container-aware)."""
    if not pids:
        logger.info("[CHROME-CLEANUP] No chrome-devtools-mcp PIDs to kill")
        return

    container_name = _resolve_container_name(user_id)
    scope = f"inside {container_name}" if container_name else "on host"
    logger.info(f"[CHROME-CLEANUP] Killing chrome-devtools-mcp PIDs {pids} {scope}")

    def _send(pid: int, name: str, const: int) -> bool:
        """Send signal; return True if process still alive after."""
        if container_name:
            try:
                probe = subprocess.run(
                    ["docker", "exec", container_name, "kill", f"-{name}", str(pid)],
                    capture_output=True, timeout=5,
                )
                return probe.returncode == 0
            except Exception as e:
                logger.warning(f"[CHROME-CLEANUP] docker exec kill failed for PID {pid}: {e}")
                return False
        try:
            os.kill(pid, const)
            return True
        except ProcessLookupError:
            return False
        except Exception as e:
            logger.warning(f"[CHROME-CLEANUP] os.kill failed for PID {pid}: {e}")
            return False

    # SIGTERM (graceful)
    for pid in pids:
        if _send(pid, "TERM", signal.SIGTERM):
            logger.info(f"[CHROME-CLEANUP] Sent SIGTERM to PID {pid}")

    time.sleep(3)

    # SIGKILL (force) for survivors
    for pid in pids:
        if container_name:
            still = _send(pid, "0", 0)  # probe
        else:
            try:
                os.kill(pid, 0)
                still = True
            except (ProcessLookupError, OSError):
                still = False
        if still:
            _send(pid, "KILL", signal.SIGKILL)
            logger.info(f"[CHROME-CLEANUP] Sent SIGKILL to PID {pid}")


def close_leftover_chrome_tabs() -> int:
    """Close leftover browser tabs on the persistent Chrome.

    Lists page targets via the CDP HTTP API and closes every tab except the
    seed about:blank (kept so Chrome doesn't exit on zero tabs). Returns the
    number of tabs closed.
    """
    # Endpoint auto-detect: container socat forwarder (:9223) first, then host (:9222).
    endpoints = [
        os.getenv("CHROME_CDP_URL", "http://172.17.0.1:9223"),
        "http://127.0.0.1:9222",
    ]
    base = None
    for ep in endpoints:
        try:
            with urllib.request.urlopen(f"{ep}/json/version", timeout=2):
                base = ep
                break
        except Exception:
            continue
    if not base:
        return 0  # Chrome unreachable (e.g. scraper-only main VPS) — nothing to close

    try:
        with urllib.request.urlopen(f"{base}/json", timeout=3) as r:
            targets = json.loads(r.read().decode())
    except Exception as e:
        logger.warning(f"[CHROME-CLEANUP] Could not list Chrome tabs: {e}")
        return 0

    closed = 0
    for t in targets:
        if t.get("type") != "page":
            continue
        if (t.get("url") or "").startswith("about:blank"):
            continue  # keep the seed tab so Chrome doesn't exit
        target_id = t.get("id")
        if not target_id:
            continue
        try:
            urllib.request.urlopen(f"{base}/json/close/{target_id}", timeout=3)
            closed += 1
        except Exception as e:
            logger.warning(f"[CHROME-CLEANUP] Failed to close tab {target_id}: {e}")
    if closed:
        logger.info(f"[CHROME-CLEANUP] Closed {closed} leftover Chrome tab(s)")
    return closed


def cleanup_after_session(user_id: Optional[int] = None, before_pids: Optional[Set[int]] = None) -> None:
    """Full post-session cleanup: kill new chrome-devtools-mcp PIDs + close tabs.

    Args:
        user_id: The project owner's user id (for container name resolution).
            None/0 => local mode (host-side cleanup).
        before_pids: Set of chrome-devtools-mcp PIDs captured BEFORE the
            session. If provided, only PIDs that are NEW (after - before) are
            killed. If None, all current PIDs are killed.
    """
    try:
        after = _get_chrome_devtools_pids(user_id)
        if before_pids is not None:
            new_pids = after - before_pids
        else:
            new_pids = after
        if new_pids:
            logger.info(f"[CHROME-CLEANUP] Reaping {len(new_pids)} new chrome-devtools-mcp PID(s): {new_pids}")
            _kill_pids(new_pids, user_id)
        else:
            logger.info("[CHROME-CLEANUP] No new chrome-devtools-mcp PIDs to clean up")
    except Exception as e:
        logger.warning(f"[CHROME-CLEANUP] PID cleanup failed (non-fatal): {e}")

    try:
        close_leftover_chrome_tabs()
    except Exception as e:
        logger.warning(f"[CHROME-CLEANUP] Tab close failed (non-fatal): {e}")
