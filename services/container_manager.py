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
    --memory=2g --cpus=2 --pids-limit=256
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
CONTAINER_PIDS_LIMIT: int = int(os.getenv("CONTAINER_PIDS_LIMIT", "256"))

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
            "--tmpfs", "/tmp:rw,size=64m,mode=1777",
            # Writable home dir for Claude (session state, .claude.json updates).
            # The rootfs is read-only, but Claude needs to write to ~/.claude/.
            # Entrypoint.sh copies config templates from /opt/claude-config/ into
            # this tmpfs on every start.
            "--tmpfs", "/home/dreampilot:rw,size=128m,mode=0700,uid=1001,gid=1001",
            # Resource limits
            "--memory", CONTAINER_MEMORY,
            "--cpus", CONTAINER_CPUS,
            "--pids-limit", str(CONTAINER_PIDS_LIMIT),
            # User mapping (entrypoint runs AS this user — no gosu needed)
            "--user", f"{CONTAINER_USER_UID}:{CONTAINER_USER_GID}",
            "--workdir", CONTAINER_MOUNT_TARGET,
            # Bind mounts
            "--mount", f"type=bind,source={self.workspace_host_path},target={CONTAINER_MOUNT_TARGET}",
            "--mount", f"type=bind,source={SHARED_CACHE_HOST},target={SHARED_CACHE_TARGET},readonly",
            # Add-host so host.docker.internal resolves to the bridge gateway.
            # Used by Claude settings.json to reach wrapper-v2 on :7861.
            "--add-host=host.docker.internal:host-gateway",
            CONTAINER_IMAGE,
        ]

    def ensure_container(self) -> str:
        """Create the container if missing, start it if stopped, return name.

        Idempotent. Called by ProjectRuntimeManager before any exec. Updates
        `user_containers.last_used_at` on every call (heartbeat for the reaper).
        """
        self.ensure_workspace()

        # Case 1: container already exists.
        if self._container_exists():
            if not self.is_running():
                logger.info("[CONTAINER] starting existing stopped container: %s", self.container_name)
                self.start()
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
        """Start the container (no-op if already running)."""
        r = _run_docker(["start", self.container_name])
        if r.returncode != 0:
            logger.warning("[CONTAINER] docker start failed: %s", r.stderr.strip())
        else:
            _set_container_status(self.user_id, "running")

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
        # The host's HOME (/root) is forwarded by the env allowlist but inside
        # the container /root is on the read-only rootfs — Claude and npx
        # need to write to $HOME for npm cache, MCP install, session state.
        args += ["-e", "HOME=/home/dreampilot"]
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
