"""
ContainerManager — per-user Docker workspace container lifecycle.

This module is the **only** place DreamAgent code talks to Docker. Every method
hits the `docker` CLI via subprocess.run (matches existing codebase style; no
Docker SDK dependency, smaller attack surface).

Container model (see docs/container_isolation.md §5)
-----------------------------------------------------
- One persistent container per user: `dreamagent-user-<user_id>`
- Bind-mount: /workspaces/user_<id> (host) → /workspace (container, rw)
- Shared cache: /srv/cache (host) → /cache (container, ro)
- Runs as uid 1001 (dreampilot), no sudo
- Flags (applied on every `docker run`):
    --cap-drop=ALL --security-opt=no-new-privileges
    --read-only --tmpfs /tmp
    --memory=2g --cpus=2 --pids-limit=1024
    --network=dreamagent-net --restart unless-stopped
- NEVER mounts: Docker socket, backend source, other users' workspaces, /root

Lifecycle (see docs/container_isolation.md §8)
----------------------------------------------
- ensure_workspace()  — create host /workspaces/user_<id>/ if missing
- ensure_container()  — create or start container, bump last_used_at
- start/stop/restart/remove
- is_running/health
- exec / exec_stream / wrap_exec  (Phase 4 / Phase 5 fill these in)
- translate_host_path
- cleanup_idle (class method, called by reaper)
- get_status_all (class method, for monitoring dashboard)

DB
--
The `user_containers` table (database_postgres.py) tracks each container's
state. `ensure_container` and lifecycle methods keep it in sync. The reaper
reads `last_used_at` to decide what to stop.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Config (defaults; all env-overridable)
# ─────────────────────────────────────────────────────────────────────

WORKSPACE_ROOT: str = os.getenv("WORKSPACE_ROOT", "/workspaces")
CONTAINER_MOUNT_TARGET: str = os.getenv("CONTAINER_MOUNT_TARGET", "/workspace")
CONTAINER_IMAGE: str = os.getenv("CONTAINER_IMAGE", "dreamagent/user-workspace:latest")
CONTAINER_NETWORK: str = os.getenv("CONTAINER_NETWORK", "dreamagent-net")
SHARED_CACHE_HOST: str = os.getenv("SHARED_CACHE_HOST", "/srv/cache")
SHARED_CACHE_TARGET: str = os.getenv("SHARED_CACHE_TARGET", "/cache")

# Resource limits — non-optional. Documented in docs/container_isolation.md §13.
CONTAINER_MEMORY: str = os.getenv("CONTAINER_MEMORY", "2g")
CONTAINER_CPUS: str = os.getenv("CONTAINER_CPUS", "2")
# PID limit. 512 was the original single-operation limit, but when a chat
# and a project creation run in parallel inside the same container they
# legitimately need ~600-800 PIDs (two Claude instances, npm install,
# vite/esbuild workers, chrome-devtools-mcp). Hitting the limit makes the
# kernel SIGKILL processes — usually the biggest one (Claude) dies first
# with exit code 137. 1024 gives headroom for parallel work without
# unbounded growth. Override via env var if needed.
CONTAINER_PIDS_LIMIT: int = int(os.getenv("CONTAINER_PIDS_LIMIT", "1024"))

# User mapping inside the container.
CONTAINER_USER_UID: int = int(os.getenv("CONTAINER_USER_UID", "1001"))
CONTAINER_USER_GID: int = int(os.getenv("CONTAINER_USER_GID", "1001"))

# Idle timeout — container stopped after this much inactivity (seconds).
CONTAINER_IDLE_TIMEOUT_SECONDS: int = int(os.getenv("CONTAINER_IDLE_TIMEOUT_SECONDS", "900"))

# Subprocess timeout for docker CLI calls (not for the containerized work itself).
_DOCKER_CMD_TIMEOUT = 30


@dataclass
class ContainerStatus:
    """Snapshot of a single container's state for the monitoring dashboard."""
    user_id: int
    container_name: str
    status: str  # running | stopped | created | errored | absent
    workspace_path: str
    last_used_at: Optional[str] = None
    cpu_percent: Optional[float] = None
    memory_used_mb: Optional[float] = None
    uptime_seconds: Optional[int] = None


def _run_docker(args: List[str], timeout: int = _DOCKER_CMD_TIMEOUT, check: bool = False) -> subprocess.CompletedProcess:
    """Run a docker CLI command. Returns CompletedProcess. Does not raise on
    non-zero exit unless check=True.

    All docker interaction in this module goes through here — single chokepoint
    for logging, timeout, and future auditing.
    """
    cmd = ["docker", *args]
    logger.debug("docker exec: %s", " ".join(shlex.quote(c) for c in cmd))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def _docker_available() -> bool:
    """True iff the docker CLI exists and the daemon is reachable."""
    try:
        r = _run_docker(["info"], timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ─────────────────────────────────────────────────────────────────────
# DB helpers — keep user_containers row in sync with reality.
# ─────────────────────────────────────────────────────────────────────

def _upsert_container_row(user_id: int, container_name: str, workspace_path: str, status: str) -> None:
    """Insert or update the user_containers row. Bumps last_used_at."""
    try:
        from database_adapter import get_db
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO user_containers
                    (user_id, container_name, workspace_path, status, last_used_at, created_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    container_name = EXCLUDED.container_name,
                    workspace_path = EXCLUDED.workspace_path,
                    status = EXCLUDED.status,
                    last_used_at = NOW()
                """,
                (user_id, container_name, workspace_path, status),
            )
            conn.commit()
    except Exception as exc:
        # DB is best-effort for tracking; the container itself is the source of truth.
        logger.warning("user_containers upsert failed (non-fatal): %s", exc)


def _set_container_status(user_id: int, status: str) -> None:
    """Update only the status column + last_used_at."""
    try:
        from database_adapter import get_db
        with get_db() as conn:
            conn.execute(
                "UPDATE user_containers SET status = %s, last_used_at = NOW() WHERE user_id = %s",
                (status, user_id),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("user_containers status update failed (non-fatal): %s", exc)


# ─────────────────────────────────────────────────────────────────────
# ContainerManager
# ─────────────────────────────────────────────────────────────────────

class ContainerManager:
    """Per-user Docker workspace container lifecycle.

    One instance per (user_id). Methods are idempotent where noted —
    `ensure_container` is the primary entry point used by ProjectRuntimeManager
    before any `docker exec`.
    """

    def __init__(self, user_id: int):
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValueError(f"user_id must be a positive int, got {user_id!r}")
        self.user_id = user_id
        self.container_name = f"dreamagent-user-{user_id}"
        self.workspace_host_path = Path(WORKSPACE_ROOT) / f"user_{user_id}"

    # ─────────────────────────────────────────────────────────────────────
    # Workspace directory
    # ─────────────────────────────────────────────────────────────────────

    def ensure_workspace(self) -> Path:
        """Create the host-side workspace dir if missing, chown 1001:1001.

        Idempotent. Returns the host path. Called on first project creation
        and on every `ensure_container` (cheap mkdir -p + conditional chown).
        """
        path = self.workspace_host_path
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            logger.info("[CONTAINER] created workspace dir: %s", path)
        # Ensure correct ownership every call — cheap and idempotent.
        # Run as root (the worker runs as root); chown to 1001:1001 so the
        # container's dreampilot user can read/write.
        if os.geteuid() == 0:
            try:
                subprocess.run(
                    ["chown", "-R", f"{CONTAINER_USER_UID}:{CONTAINER_USER_GID}", str(path)],
                    check=False,
                    capture_output=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                logger.warning("[CONTAINER] chown timed out on %s", path)
        return path

    # ─────────────────────────────────────────────────────────────────────
    # Container lifecycle
    # ─────────────────────────────────────────────────────────────────────

    def _build_run_args(self) -> List[str]:
        """Build the `docker run` arg list with all hardening flags."""
        return [
            "run",
            "-d",
            "--name", self.container_name,
            "--network", CONTAINER_NETWORK,
            "--restart", "unless-stopped",
            # Hardening (non-optional — see docs/container_isolation.md §13)
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            # /tmp must be large enough for npm cache (~300MB) + build artifacts.
            # 64MB was too small — caused "ENOSPC" during npm ci / vite build.
            "--tmpfs", "/tmp:rw,size=512m,mode=1777",
            # Writable home dir for Claude (session state, .claude.json updates).
            # The rootfs is read-only, but Claude needs to write to ~/.claude/.
            # Entrypoint.sh copies config templates from /opt/claude-config/ into
            # this tmpfs on every start. 256MB allows npm to use ~/.npm as fallback.
            "--tmpfs", "/home/dreampilot:rw,size=256m,mode=0700,uid=1001,gid=1001",
            # Resource limits
            "--memory", CONTAINER_MEMORY,
            "--cpus", CONTAINER_CPUS,
            "--pids-limit", str(CONTAINER_PIDS_LIMIT),
            # User mapping (entrypoint runs AS this user — no gosu needed)
            "--user", f"{CONTAINER_USER_UID}:{CONTAINER_USER_GID}",
            "--workdir", CONTAINER_MOUNT_TARGET,
            # Bind mounts
            "--mount", f"type=bind,source={self.workspace_host_path},target={CONTAINER_MOUNT_TARGET}",
            # /cache is writable (rw) — npm and pip need to write cached packages.
            # Making it read-only defeated the entire purpose of a shared cache.
            "--mount", f"type=bind,source={SHARED_CACHE_HOST},target={SHARED_CACHE_TARGET}",
            # Add-host so host.docker.internal resolves to the bridge gateway.
            # Used by Claude settings.json to reach wrapper-v2 on :7861.
            "--add-host=host.docker.internal:host-gateway",
            CONTAINER_IMAGE,
        ]

    def ensure_container(self) -> str:
        """Create the container if missing, start it if stopped, return name.

        Idempotent. Called by ProjectRuntimeManager before any exec. Updates
        `user_containers.last_used_at` on every call (heartbeat for the reaper).

        Also detects container restarts (Docker daemon restart, VPS reboot)
        by checking the container's actual start time. If the container was
        recently restarted, clears stale Claude session IDs (tmpfs is wiped
        on restart → old resume IDs are dead).
        """
        self.ensure_workspace()

        # Case 1: container already exists.
        if self._container_exists():
            if not self.is_running():
                logger.info("[CONTAINER] starting existing stopped container: %s", self.container_name)
                self.start()
            else:
                # Container is running — but was it recently restarted?
                # (Docker daemon restart auto-starts containers via --restart
                # unless-stopped, which bypasses our start() cleanup.)
                self._check_restart_and_cleanup()
            _set_container_status(self.user_id, "running")
            return self.container_name

        # Case 2: need to create.
        if not _docker_available():
            raise RuntimeError("docker daemon not available — cannot create container")

        logger.info("[CONTAINER] creating container: %s (image=%s)", self.container_name, CONTAINER_IMAGE)
        args = self._build_run_args()
        result = _run_docker(args, timeout=60)
        if result.returncode != 0:
            logger.error("[CONTAINER] docker run failed: %s", result.stderr.strip())
            raise RuntimeError(f"docker run failed: {result.stderr.strip()}")

        container_id = result.stdout.strip()
        logger.info("[CONTAINER] created %s (id=%s)", self.container_name, container_id[:12])

        _upsert_container_row(
            user_id=self.user_id,
            container_name=self.container_name,
            workspace_path=str(self.workspace_host_path),
            status="running",
        )
        return self.container_name

    def _container_exists(self) -> bool:
        """True iff a container with our name exists (any state)."""
        r = _run_docker(["ps", "--all", "--filter", f"name=^{self.container_name}$", "--format", "{{.Names}}"])
        if r.returncode != 0:
            return False
        return self.container_name in r.stdout.strip().splitlines()

    def start(self) -> None:
        """Start the container (no-op if already running).

        Clears stale Claude session resume IDs for this user because the
        tmpfs (/home/dreampilot) is wiped on every container restart.
        Without this, Claude tries to --resume a non-existent session and
        exits with code 1.
        """
        r = _run_docker(["start", self.container_name])
        if r.returncode != 0:
            logger.warning("[CONTAINER] docker start failed: %s", r.stderr.strip())
        else:
            _set_container_status(self.user_id, "running")
            self._clear_stale_session_ids()

    def _check_restart_and_cleanup(self) -> None:
        """Detect if the container was restarted since last use.

        Compares the container's actual start time (from docker inspect)
        with the last_used_at timestamp in the DB. If the container started
        AFTER the last use, the tmpfs was wiped → clear stale session IDs.

        This catches Docker daemon restarts and VPS reboots where the
        container auto-starts via --restart unless-stopped (bypassing our
        start() cleanup).
        """
        try:
            # Get the container's actual start time
            r = _run_docker([
                "inspect", "--format", "{{.State.StartedAt}}",
                self.container_name,
            ])
            if r.returncode != 0 or not r.stdout.strip():
                return

            container_started_str = r.stdout.strip()
            # Docker returns ISO 8601 format: 2026-07-19T02:11:34.123456789Z
            # Parse it to a comparable value (strip nanoseconds to microseconds)
            import datetime as _dt
            try:
                # Handle nanoseconds by truncating to 6 digits
                if "." in container_started_str:
                    parts = container_started_str.split(".")
                    ts_part = parts[1].rstrip("Z")
                    ts_part = ts_part[:6]  # microseconds max
                    container_started_str = parts[0] + "." + ts_part + "Z"
                container_started = _dt.datetime.fromisoformat(
                    container_started_str.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                return

            # Get last_used_at from DB
            from database_adapter import get_db
            with get_db() as conn:
                row = conn.execute(
                    "SELECT last_used_at FROM user_containers WHERE user_id = %s",
                    (self.user_id,),
                ).fetchone()

            if not row:
                return

            last_used = row["last_used_at"] if isinstance(row, dict) else row[0]
            if not last_used:
                return

            # last_used_at is timezone-naive (from PostgreSQL NOW()), convert to UTC
            if last_used.tzinfo is None:
                last_used = last_used.replace(tzinfo=_dt.timezone.utc)

            # If container started AFTER the last use → it was restarted
            if container_started > last_used:
                logger.info(
                    "[CONTAINER] detected restart for %s (started=%s, last_used=%s) — clearing session IDs",
                    self.container_name,
                    container_started_str,
                    last_used.isoformat(),
                )
                self._clear_stale_session_ids()
        except Exception as exc:
            logger.debug("[CONTAINER] restart check failed (non-fatal): %s", exc)

    def _clear_stale_session_ids(self) -> None:
        """Delete ALL claude_session_resumes rows for this user's projects.

        Called after container (re)start. The tmpfs at /home/dreampilot is
        ephemeral — Claude's session state files don't survive restarts, so
        any stored session IDs are stale and must be cleared to prevent
        'claude --resume <dead-id>' failures.
        """
        try:
            from database_adapter import get_db
            with get_db() as conn:
                # Get ALL project paths for this user
                rows = conn.execute(
                    "SELECT project_path FROM projects WHERE user_id = %s",
                    (self.user_id,),
                ).fetchall()
                paths = []
                for row in rows:
                    p = row["project_path"] if isinstance(row, dict) else row[0]
                    if p:
                        paths.append(p)

                if paths:
                    # Delete ALL resume entries for ALL of this user's projects.
                    # Simple and robust — no LIKE pattern matching issues.
                    for path in paths:
                        conn.execute(
                            "DELETE FROM claude_session_resumes WHERE resume_key LIKE %s",
                            (f"{path}%",),
                        )
                    # Also clear by frontend_src_path variant (resume keys may use
                    # /frontend/src instead of just the project root)
                    for path in paths:
                        conn.execute(
                            "DELETE FROM claude_session_resumes WHERE resume_key LIKE %s",
                            (f"{path}/frontend%",),
                        )
                    conn.commit()
                    logger.info(
                        "[CONTAINER] cleared stale Claude session IDs for user %s (%d projects)",
                        self.user_id, len(paths),
                    )
        except Exception as exc:
            logger.warning("[CONTAINER] session ID cleanup failed (non-fatal): %s", exc)

    def stop(self) -> None:
        """Stop the container (preserves volume, state survives)."""
        r = _run_docker(["stop", self.container_name], timeout=30)
        if r.returncode != 0:
            logger.warning("[CONTAINER] docker stop failed: %s", r.stderr.strip())
        else:
            _set_container_status(self.user_id, "stopped")
            logger.info("[CONTAINER] stopped %s", self.container_name)

    def restart(self) -> None:
        """Restart the container — used for self-heal on health failure."""
        r = _run_docker(["restart", self.container_name], timeout=60)
        if r.returncode != 0:
            logger.warning("[CONTAINER] docker restart failed: %s", r.stderr.strip())
        else:
            _set_container_status(self.user_id, "running")
            logger.info("[CONTAINER] restarted %s", self.container_name)

    def remove(self, force: bool = True) -> None:
        """Remove the container entirely. Called on user deletion."""
        args = ["rm"]
        if force:
            args.append("-f")
        args.append(self.container_name)
        r = _run_docker(args, timeout=30)
        if r.returncode != 0 and "No such container" not in r.stderr:
            logger.warning("[CONTAINER] docker rm failed: %s", r.stderr.strip())
        # Clear DB row
        try:
            from database_adapter import get_db
            with get_db() as conn:
                conn.execute("DELETE FROM user_containers WHERE user_id = %s", (self.user_id,))
                conn.commit()
        except Exception as exc:
            logger.warning("[CONTAINER] DB row delete failed (non-fatal): %s", exc)

    def is_running(self) -> bool:
        """True iff container exists and is in running state."""
        r = _run_docker([
            "ps", "--filter", f"name=^{self.container_name}$",
            "--filter", "status=running",
            "--format", "{{.Names}}",
        ])
        return r.returncode == 0 and self.container_name in r.stdout.strip().splitlines()

    def has_active_claude(self) -> bool:
        """True if a Claude CLI process is currently running inside this container.

        Used by project-creation to detect when a parallel chat is in flight
        so it can skip the pre-run cleanup_processes() (which would SIGKILL
        the chat's Claude). Also used by the container reaper to avoid stopping
        containers with active sessions.

        Detection strategy (multi-layered):
          1. PID file check: ClaudeCodeAgent writes /tmp/.claude_active_pid on
             spawn and removes it on completion. If the file exists AND the PID
             is alive, Claude is active.
          2. Process scan fallback: scan /proc/*/cmdline for the claude CLI
             binary path (@anthropic-ai/claude-code). Excludes MCP servers
             (chrome-devtools-mcp, zai-mcp) and our own detection shell.

        The PID file is the primary signal — set by mark_claude_active() and
        cleared by mark_claude_inactive(). The process scan is a safety net
        for cases where the PID file wasn't written (e.g. older code paths).
        """
        if not self._container_exists():
            return False

        # Layer 1: PID file check (fast, reliable, no false positives)
        pid_r = _run_docker([
            "exec", self.container_name,
            "sh", "-c",
            # Read the PID file and check if that PID is still alive
            "PID=$(cat /tmp/.claude_active_pid 2>/dev/null); "
            "if [ -n \"$PID\" ] && kill -0 \"$PID\" 2>/dev/null; then echo yes; exit 0; fi; "
            "echo no",
        ], timeout=5)
        if pid_r.returncode == 0 and pid_r.stdout.strip() == "yes":
            return True

        # Layer 2: Process scan fallback (safety net)
        r = _run_docker([
            "exec", self.container_name,
            "sh", "-c",
            # Scan /proc/*/cmdline for the claude CLI package path.
            # Obfuscate 'anthropic' to avoid self-match.
            "for f in /proc/[0-9]*/cmdline; do "
            "  if tr '\\0' ' ' < \"$f\" 2>/dev/null | grep -q \"cl$(echo aude)-code\"; then "
            "    # Exclude MCP servers that are children of claude, not claude itself "
            "    PID=$(echo \"$f\" | grep -o '[0-9]*'); "
            "    CMD=$(tr '\\0' ' ' < \"$f\" 2>/dev/null); "
            "    case \"$CMD\" in "
            "      *chrome-devtools*|*zai-mcp*|*mcp-server*) continue;; "
            "      *) echo yes; exit 0;; "
            "    esac; "
            "  fi; "
            "done; echo no",
        ], timeout=8)
        if r.returncode == 0 and r.stdout.strip() == "yes":
            return True

        return False

    def mark_claude_active(self, pid: int) -> None:
        """Write the active Claude PID to a file inside the container.

        Called by ClaudeCodeAgent.start() after spawning the CLI subprocess.
        The reaper and project-creation check this file via has_active_claude().
        """
        if not self._container_exists():
            return
        _run_docker([
            "exec", self.container_name,
            "sh", "-c", f"echo {pid} > /tmp/.claude_active_pid",
        ], timeout=5)

    def mark_claude_inactive(self) -> None:
        """Remove the active Claude PID file.

        Called by ClaudeCodeAgent.stop() / finally block after the query
        completes. Signals to the reaper that the container can be reaped.
        """
        if not self._container_exists():
            return
        _run_docker([
            "exec", self.container_name,
            "sh", "-c", "rm -f /tmp/.claude_active_pid",
        ], timeout=5)

    def cleanup_processes(self, spare_patterns: Optional[List[str]] = None) -> int:
        """Kill processes inside the container except PID 1 and any matching spare_patterns.

        Previous ACPX/build/MCP processes accumulate inside the container
        (orphaned npm, esbuild, node, chrome-devtools processes). This
        cleans them up before starting a new exec session.

        CRITICAL: by default this SPARES active Claude CLI processes and
        chrome-devtools-mcp servers, because the same user container may be
        running an active chat in parallel with project creation. Killing
        those would SIGKILL the chat (exit code 137) and lose the user's
        in-flight conversation.

        Args:
            spare_patterns: substrings matched against each process's
                /proc/<pid>/cmdline. If a process matches ANY pattern, it is
                NOT killed. Defaults to claude + chrome-devtools-mcp so
                active chats survive parallel project creation.

        Returns the number of processes killed.
        """
        if spare_patterns is None:
            # By default, spare anything that looks like an active Claude
            # chat session or its chrome-devtools MCP server.
            spare_patterns = ["claude", "chrome-devtools-mcp"]

        # List all PIDs except PID 1
        r = _run_docker([
            "exec", self.container_name,
            "sh", "-c",
            "for p in /proc/[0-9]*; do pid=$(basename $p); [ $pid -gt 1 ] && echo $pid; done 2>/dev/null",
        ], timeout=10)
        if r.returncode != 0 or not r.stdout.strip():
            return 0

        pids = [p.strip() for p in r.stdout.strip().splitlines() if p.strip().isdigit()]
        killed = 0
        spared = 0
        for pid in pids:
            # Read the process's cmdline to decide if it should be spared.
            cmdline = ""
            if spare_patterns:
                cmd_r = _run_docker([
                    "exec", self.container_name,
                    "sh", "-c", f"tr '\\0' ' ' < /proc/{pid}/cmdline 2>/dev/null",
                ], timeout=3)
                if cmd_r.returncode == 0:
                    cmdline = cmd_r.stdout

            if spare_patterns and any(pat in cmdline for pat in spare_patterns):
                spared += 1
                logger.info(
                    "[CONTAINER] sparing pid=%s in %s (cmdline matches keepalive pattern %r): %s",
                    pid, self.container_name,
                    next(p for p in spare_patterns if p in cmdline),
                    cmdline[:120],
                )
                continue

            kr = _run_docker(["exec", self.container_name, "kill", "-9", pid], timeout=5)
            if kr.returncode == 0:
                killed += 1
                logger.debug("[CONTAINER] killed pid=%s in %s: %s", pid, self.container_name, cmdline[:80])

        if killed or spared:
            logger.info(
                "[CONTAINER] cleanup in %s: killed %d, spared %d (keepalive: %s)",
                self.container_name, killed, spared, spare_patterns,
            )
        return killed

    def health(self) -> Dict[str, Any]:
        """Return CPU/mem/uptime via `docker inspect` + `docker stats`.

        Shape mirrors what the monitoring dashboard expects per container.
        Returns dict with status='absent' if container doesn't exist.
        """
        if not self._container_exists():
            return {"user_id": self.user_id, "status": "absent", "container_name": self.container_name}

        # Inspect for state + start time
        inspect_r = _run_docker([
            "inspect",
            "--format", "{{.State.Status}}|{{.State.StartedAt}}|{{.Name}}",
            self.container_name,
        ])
        info: Dict[str, Any] = {"user_id": self.user_id, "container_name": self.container_name}
        if inspect_r.returncode == 0:
            try:
                status_str, started_at, _name = inspect_r.stdout.strip().split("|", 2)
                info["status"] = status_str
                info["started_at"] = started_at
            except ValueError:
                info["status"] = "unknown"

        # Stats (no-stream for one-shot read)
        stats_r = _run_docker([
            "stats", "--no-stream",
            "--format", "{{.CPUPerc}}|{{.MemUsage}}",
            self.container_name,
        ], timeout=15)
        if stats_r.returncode == 0 and stats_r.stdout.strip():
            try:
                cpu_str, mem_str = stats_r.stdout.strip().split("|", 2)[:2]
                info["cpu_percent"] = float(cpu_str.strip().rstrip("%"))
                # mem_str like "123.4MiB / 2.000GiB"
                mem_used = mem_str.split("/")[0].strip()
                info["memory_used"] = mem_used
            except (ValueError, IndexError):
                pass

        return info

    # ─────────────────────────────────────────────────────────────────────
    # Execution
    # ─────────────────────────────────────────────────────────────────────

    def get_container_ip(self) -> Optional[str]:
        """Get the container's IP on the dreamagent-net bridge network.

        This IP is reachable from the host and from Chrome on the host.
        Used by Claude inside the container to construct URLs that the
        shared Chrome DevTools MCP can actually reach (localhost inside
        the container is NOT reachable from host Chrome).

        Returns:
            IP address string (e.g. "172.18.0.2") or None if unavailable.
        """
        try:
            r = _run_docker([
                "inspect", "--format",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                self.container_name,
            ])
            if r.returncode == 0 and r.stdout.strip():
                ip = r.stdout.strip()
                logger.debug("[CONTAINER] %s IP: %s", self.container_name, ip)
                return ip
        except Exception:
            pass
        return None

    def wrap_exec(
        self,
        command: List[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """Build the full `docker exec ...` command list for a base command.

        Used by ProjectRuntimeManager.wrap_command when EXECUTION_MODE=container.
        Translates host cwd to in-container path, injects env via -e flags,
        and pins the user to uid:gid 1001.

        Phase 4 implementation (called from ProjectRuntimeManager).
        """
        # Ensure container is up before constructing the exec command.
        # (ProjectRuntimeManager should already have called ensure_container,
        # but this is a cheap belt-and-suspenders check.)
        self.ensure_container()

        args: List[str] = [
            "docker",
            "exec",
            "--user", f"{CONTAINER_USER_UID}:{CONTAINER_USER_GID}",
        ]

        # Working directory: translate host path to in-container path.
        if cwd:
            in_container_cwd = self.translate_host_path(cwd)
            args += ["--workdir", in_container_cwd]

        # Env vars: each as a separate -e flag.
        # Always override HOME to /home/dreampilot (the writable tmpfs).
        args += ["-e", "HOME=/home/dreampilot"]

        # Inject CONTAINER_IP so Claude can construct URLs that host Chrome
        # can reach. Without this, Claude uses localhost which only works
        # inside the container — Chrome on the host can't connect.
        container_ip = self.get_container_ip()
        if container_ip:
            args += ["-e", f"CONTAINER_IP={container_ip}"]
            args += ["-e", f"CHROME_VERIFY_URL=http://{container_ip}"]

        # Inject PROJECT_ID and host API URL so buildpublish.py inside the
        # container can call back to the worker-api to restart PM2 (the
        # sandbox/container can't access PM2 directly). The worker-api runs
        # on the SAME host as PM2 (the worker VPS), reachable via
        # host.docker.internal (set via --add-host above) on port 8003.
        # Note: 8002 is the MAIN VPS API — not reachable from the container.
        # 8003 is the worker-api which has direct PM2 access.
        args += ["-e", f"DREAMPILOT_PROJECT_ID={self.user_id}"]
        args += ["-e", "DREAMPILOT_WORKER_API_URL=http://host.docker.internal:8003"]

        if env:
            for k, v in env.items():
                # Skip empty/None values to avoid docker CLI quirks.
                # Skip HOME — we override it above.
                if k == "HOME":
                    continue
                if v is not None and v != "":
                    args += ["-e", f"{k}={v}"]

        args.append(self.container_name)
        args.extend(command)
        return args

    def exec(
        self,
        command: List[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> subprocess.CompletedProcess:
        """Sync `docker exec` — Phase 5 build path (npm/pip).

        Wraps the exec with the docker CLI. Returns a CompletedProcess
        identical in shape to subprocess.run's return.
        """
        full_cmd = ["docker", *self.wrap_exec(command, cwd=cwd, env=env)]
        logger.debug("[CONTAINER] exec: %s", " ".join(shlex.quote(c) for c in full_cmd[:8]))
        return subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    async def exec_stream(
        self,
        command: List[str],
        *,
        cwd: str,
        env: Dict[str, str],
        stdout_limit: int = 10 * 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        """Async `docker exec` with streaming stdout — Phase 4 Claude path.

        Yields stdout lines as bytes. Caller parses stream-json exactly as
        today; the docker exec stdout is a pipe just like asyncio's.
        """
        import asyncio
        full_cmd = ["docker", *self.wrap_exec(command, cwd=cwd, env=env)]
        logger.debug("[CONTAINER] exec_stream: %s", " ".join(shlex.quote(c) for c in full_cmd[:8]))

        process = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=stdout_limit,
            start_new_session=True,
        )
        # Stream stdout line by line.
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            yield line
        await process.wait()

    # ─────────────────────────────────────────────────────────────────────
    # Path translation
    # ─────────────────────────────────────────────────────────────────────

    def translate_host_path(self, host_path: str) -> str:
        """Convert a host workspace path to its in-container equivalent.

        /workspaces/user_42/website/<proj>  →  /workspace/website/<proj>

        Leaves non-workspace paths unchanged (and logs a warning — those
        shouldn't be passed in container mode).
        """
        workspace_prefix = WORKSPACE_ROOT + "/"
        if host_path.startswith(workspace_prefix):
            remainder = host_path[len(workspace_prefix):]
            # remainder looks like "user_42/website/<proj>"
            slash_idx = remainder.find("/")
            if slash_idx == -1:
                return CONTAINER_MOUNT_TARGET
            rest = remainder[slash_idx + 1:]  # website/<proj>
            return posixpath.join(CONTAINER_MOUNT_TARGET, rest)

        logger.warning(
            "translate_host_path: path %r is not under workspace root %r — returning unchanged",
            host_path,
            WORKSPACE_ROOT,
        )
        return host_path

    # ─────────────────────────────────────────────────────────────────────
    # Class-level utilities
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def cleanup_idle(cls, idle_timeout_seconds: int = CONTAINER_IDLE_TIMEOUT_SECONDS) -> int:
        """Stop containers idle longer than the threshold. Returns count stopped.

        Called by the reaper script (PM2-managed, 60s loop). Reads
        `user_containers.last_used_at`, issues `docker stop` for each,
        updates status to 'stopped'.
        """
        if not _docker_available():
            return 0

        try:
            from database_adapter import get_db
            with get_db() as conn:
                rows = conn.execute(
                    """
                    SELECT user_id, container_name
                    FROM user_containers
                    WHERE status = 'running'
                      AND last_used_at < NOW() - (%s * INTERVAL '1 second')
                    """,
                    (idle_timeout_seconds,),
                ).fetchall()
        except Exception as exc:
            logger.warning("[REAPER] DB query failed: %s", exc)
            return 0

        stopped = 0
        for row in rows:
            user_id = row["user_id"] if isinstance(row, dict) else row[0]
            container_name = row["container_name"] if isinstance(row, dict) else row[1]
            # Double-check it's actually still running before stopping.
            r = _run_docker([
                "ps", "--filter", f"name=^{container_name}$",
                "--filter", "status=running", "--format", "{{.Names}}",
            ])
            if r.returncode == 0 and container_name in r.stdout.strip().splitlines():
                # CRITICAL: don't stop if the container has active Claude processes.
                # Long-running operations (telegram editor, scheduler editor,
                # project creation) run Claude inside the container for up to
                # 20 minutes WITHOUT bumping last_used_at (they're not going
                # through ensure_container on every loop). The reaper would
                # kill the container mid-edit → exit code 137 → rollback.
                # Check for claude processes before stopping.
                cm = cls(user_id)
                if cm.has_active_claude():
                    logger.info(
                        "[REAPER] skipping %s — Claude is actively running (user_id=%s)",
                        container_name, user_id,
                    )
                    continue

                logger.info("[REAPER] stopping idle container: %s (user_id=%s)", container_name, user_id)
                stop_r = _run_docker(["stop", container_name], timeout=30)
                if stop_r.returncode == 0:
                    stopped += 1
                    try:
                        with get_db() as conn:
                            conn.execute(
                                "UPDATE user_containers SET status = 'stopped' WHERE user_id = %s",
                                (user_id,),
                            )
                            conn.commit()
                    except Exception:
                        pass
        return stopped

    @classmethod
    def get_status_all(cls) -> List[ContainerStatus]:
        """Return status for every user container — for the monitoring dashboard.

        Joins the user_containers DB rows with `docker ps` for live state.
        """
        results: List[ContainerStatus] = []

        # Live containers from docker
        live_names: Dict[str, Dict[str, Any]] = {}
        if _docker_available():
            r = _run_docker([
                "ps", "--all",
                "--filter", "name=dreamagent-user-",
                "--format", "{{.Names}}|{{.Status}}|{{.RunningFor}}",
            ])
            if r.returncode == 0:
                for line in r.stdout.strip().splitlines():
                    if not line:
                        continue
                    try:
                        name, status, running_for = line.split("|", 2)
                        # Extract user_id from name
                        if name.startswith("dreamagent-user-"):
                            uid_str = name[len("dreamagent-user-"):]
                            uid = int(uid_str) if uid_str.isdigit() else 0
                            live_names[name] = {
                                "user_id": uid,
                                "status": "running" if status.startswith("Up") else "stopped",
                                "running_for": running_for,
                            }
                    except (ValueError, IndexError):
                        continue

        # DB rows (for workspace_path + last_used_at)
        try:
            from database_adapter import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT user_id, container_name, workspace_path, status, last_used_at FROM user_containers"
                ).fetchall()
        except Exception as exc:
            logger.warning("[CONTAINER] DB query failed in get_status_all: %s", exc)
            rows = []

        for row in rows:
            user_id = row["user_id"] if isinstance(row, dict) else row[0]
            container_name = row["container_name"] if isinstance(row, dict) else row[1]
            workspace_path = row["workspace_path"] if isinstance(row, dict) else row[2]
            db_status = row["status"] if isinstance(row, dict) else row[3]
            last_used = row["last_used_at"] if isinstance(row, dict) else row[4]

            # Prefer live status over DB status where available.
            live = live_names.get(container_name)
            live_status = live["status"] if live else "absent"

            results.append(ContainerStatus(
                user_id=user_id,
                container_name=container_name,
                status=live_status if live else db_status,
                workspace_path=workspace_path,
                last_used_at=str(last_used) if last_used else None,
            ))

        return results
