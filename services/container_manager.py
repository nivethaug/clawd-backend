"""
ContainerManager — per-user Docker workspace container lifecycle.

This module is the **only** place DreamAgent code talks to Docker. It exposes
the full v1 API surface (every method the rest of the codebase will eventually
need) but DOES NOT implement any of it yet. Every method raises
`NotImplementedError`. This keeps Phase 1 a pure refactor: callers can be wired
to ContainerManager through ProjectRuntimeManager, but since EXECUTION_MODE
defaults to "local", none of these stubs are ever reached.

Implementation lands in Phase 3 (per docs/container_migration_phase0.md).

Why stub the full API now
-------------------------
Phase 1's goal is to land the abstraction without behavior change. By defining
the complete contract today, Phase 4 (Claude in container) and Phase 5 (build
in container) can be written against a stable interface — they don't need to
invent method signatures mid-migration. The stub also makes it impossible to
accidentally enable container mode before the implementation exists: any call
into ContainerManager raises immediately and loudly.

Container model (for reference; implemented in Phase 3)
-------------------------------------------------------
- One persistent container per user: `dreamagent-user-<user_id>`
- Bind-mount: `/workspaces/user_<id>` (host) → `/workspace` (container, rw)
- Shared cache: `/srv/cache` (host) → `/cache` (container, ro)
- Runs as uid 1001, no sudo
- Flags: --cap-drop=ALL --security-opt=no-new-privileges --read-only --tmpfs /tmp
         --memory=2g --cpus=2 --pids-limit=256 --network=dreamagent-net
         --restart unless-stopped
- NEVER mounts: Docker socket, backend source, other users' workspaces, /root

All Docker interaction uses `subprocess.run(["docker", ...])` (matches existing
codebase style; no Docker SDK dependency).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Config (defaults; all env-overridable in Phase 3)
# ─────────────────────────────────────────────────────────────────────

# Host-side root for per-user workspace directories.
WORKSPACE_ROOT: str = "/workspaces"

# In-container mount target for the user's workspace.
CONTAINER_MOUNT_TARGET: str = "/workspace"

# Docker image tag for the per-user workspace container.
CONTAINER_IMAGE: str = "dreamagent/user-workspace:latest"

# Dedicated bridge network (egress-limited in Phase 3).
CONTAINER_NETWORK: str = "dreamagent-net"

# Resource limits — non-optional once Phase 3 ships. Documented here so the
# values are visible without grepping the implementation later.
CONTAINER_MEMORY: str = "2g"
CONTAINER_CPUS: str = "2"
CONTAINER_PIDS_LIMIT: int = 256

# User mapping inside the container.
CONTAINER_USER_UID: int = 1001
CONTAINER_USER_GID: int = 1001

# Idle timeout — container stopped after this much inactivity (seconds).
CONTAINER_IDLE_TIMEOUT_SECONDS: int = 900


@dataclass
class ContainerStatus:
    """Snapshot of a single container's state for the monitoring dashboard."""
    user_id: int
    container_name: str
    status: str  # created | running | stopped | errored | absent
    workspace_path: str
    last_used_at: Optional[str] = None
    cpu_percent: Optional[float] = None
    memory_used_mb: Optional[float] = None
    uptime_seconds: Optional[int] = None


class ContainerManager:
    """Per-user Docker workspace container lifecycle.

    One instance per (user_id). Methods are intentionally side-effectful and
    idempotent where noted — `ensure_container` is the primary entry point,
    used by ProjectRuntimeManager before any `docker exec`.
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

        Phase 3 implementation.
        """
        raise NotImplementedError("ContainerManager.ensure_workspace lands in Phase 3.")

    # ─────────────────────────────────────────────────────────────────────
    # Container lifecycle
    # ─────────────────────────────────────────────────────────────────────

    def ensure_container(self) -> str:
        """Create the container if missing, start it if stopped, return name.

        Idempotent. Called by ProjectRuntimeManager before any exec. Updates
        `user_containers.last_used_at` on every call (heartbeat for the reaper).

        Phase 3 implementation.
        """
        raise NotImplementedError("ContainerManager.ensure_container lands in Phase 3.")

    def start(self) -> None:
        """Start the container (no-op if already running). Phase 3."""
        raise NotImplementedError("ContainerManager.start lands in Phase 3.")

    def stop(self) -> None:
        """Stop the container (preserves volume, state survives). Phase 3 / reaper."""
        raise NotImplementedError("ContainerManager.stop lands in Phase 3.")

    def restart(self) -> None:
        """Restart the container — used for self-heal on health failure. Phase 3."""
        raise NotImplementedError("ContainerManager.restart lands in Phase 3.")

    def remove(self, force: bool = True) -> None:
        """Remove the container entirely. Called on user deletion. Phase 3."""
        raise NotImplementedError("ContainerManager.remove lands in Phase 3.")

    def is_running(self) -> bool:
        """True iff container exists and is in running state. Phase 3."""
        raise NotImplementedError("ContainerManager.is_running lands in Phase 3.")

    def health(self) -> Dict[str, Any]:
        """Return CPU/mem/uptime via `docker inspect` + `docker stats`. Phase 3.

        Shape mirrors what the monitoring dashboard expects per container.
        """
        raise NotImplementedError("ContainerManager.health lands in Phase 3.")

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
        Translates host cwd to in-container path, injects env via `-e` flags,
        and pins the user to uid:gid 1001.

        Phase 4 implementation (called from ProjectRuntimeManager).
        """
        raise NotImplementedError("ContainerManager.wrap_exec lands in Phase 4.")

    def exec(
        self,
        command: List[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> "subprocess.CompletedProcess":  # type: ignore[name-defined]
        """Sync `docker exec` — Phase 5 build path (npm/pip).

        Wraps the exec with `timeout(1)` for wall-clock cap. Returns a
        CompletedProcess identical in shape to subprocess.run's return.
        """
        raise NotImplementedError("ContainerManager.exec lands in Phase 5.")

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
        raise NotImplementedError("ContainerManager.exec_stream lands in Phase 4.")
        # Yield required to make this an async generator type-wise even though
        # the body is unreachable until Phase 4.
        yield b""  # pragma: no cover

    # ─────────────────────────────────────────────────────────────────────
    # Path translation
    # ─────────────────────────────────────────────────────────────────────

    def translate_host_path(self, host_path: str) -> str:
        """Convert a host workspace path to its in-container equivalent.

        /workspaces/user_42/website/<proj>  →  /workspace/website/<proj>

        Leaves non-workspace paths unchanged (and logs a warning — those
        shouldn't be passed in container mode).

        Phase 4 implementation (used by wrap_exec).
        """
        raise NotImplementedError("ContainerManager.translate_host_path lands in Phase 4.")

    # ─────────────────────────────────────────────────────────────────────
    # Class-level utilities
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def cleanup_idle(cls, idle_timeout_seconds: int = CONTAINER_IDLE_TIMEOUT_SECONDS) -> int:
        """Stop containers idle longer than the threshold. Returns count stopped.

        Called by the reaper script (PM2-managed, 60s loop) in Phase 3.
        Reads `user_containers.last_used_at`, issues `docker stop` for each,
        updates status to 'stopped'.
        """
        raise NotImplementedError("ContainerManager.cleanup_idle lands in Phase 3.")

    @classmethod
    def get_status_all(cls) -> List[ContainerStatus]:
        """Return status for every user container — for the monitoring dashboard.

        Phase 3 implementation (extends services/system_metrics.py).
        """
        raise NotImplementedError("ContainerManager.get_status_all lands in Phase 3.")
