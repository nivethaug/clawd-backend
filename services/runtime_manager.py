"""
ProjectRuntimeManager — abstraction layer over where user-influenced commands run.

This is the single decision point that determines whether a command executes on
the worker host (today's behavior) or inside a per-user Docker container (the
v1 container-isolation target).

Why this exists
---------------
DreamAgent code that executes user-influenced code (Claude, npm, pip, builds)
has historically called `subprocess.run` / `asyncio.create_subprocess_exec`
directly, wrapped with `sudo -u dreampilot`. As we move that code into
per-user Docker containers, every call site would otherwise need a fork:

    if EXECUTION_MODE == "container":
        # docker exec ...
    else:
        # sudo -u dreampilot ...

ProjectRuntimeManager absorbs that fork in one place. Today (Phase 1) it only
ever executes locally — the container branch is a stub. Phase 4 will flesh out
the container branch without touching any caller.

API
---
- `exec_subprocess(...)`        → sync subprocess.run equivalent
- `exec_subprocess_stream(...)` → async subprocess stream equivalent (for Claude)

Both build the right command (local `sudo -u dreampilot` vs container
`docker exec -u 1001:1001`) based on `EXECUTION_MODE` and `user_id`, then hand
off to `subprocess` or `ContainerManager` respectively.

Backward compatibility
----------------------
When `EXECUTION_MODE=local` (default), the command and wrapping are identical
to what callers did inline before this refactor. No observable behavior change.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Optional, Union, List, Dict, Any

logger = logging.getLogger(__name__)


# Resolved once at module import (matching how the rest of the codebase reads env).
# Valid values: "local" (default, today's behavior) | "container" (per-user Docker)
EXECUTION_MODE: str = os.getenv("EXECUTION_MODE", "local").lower().strip()

# The host user that claude/npm/pip historically run as. Only used in local mode.
# Mirrors claude_code_agent.py:134 / 807 (CLAUDE_RUN_AS_USER env, default "dreampilot").
LOCAL_RUN_AS_USER: str = os.getenv("CLAUDE_RUN_AS_USER", "dreampilot")


@dataclass
class RuntimeSpawnResult:
    """Result of an async spawn — wraps the asyncio subprocess object.

    Returned by `exec_subprocess_stream` so callers can read stdout/stderr
    line by line exactly as they did with the raw asyncio process. Both the
    local and container code paths return the same shape.
    """
    process: asyncio.subprocess.Process
    # Host path the caller asked for; preserved for logging.
    requested_cwd: str
    # The actual command that was spawned (post sudo/docker-exec wrapping).
    effective_command: List[str]


class ProjectRuntimeManager:
    """Decides where a command runs (host vs container) and builds the spawn.

    Construct one per execution context. For local mode, `user_id` is unused.
    For container mode (Phase 4+), `user_id` selects which user's container to
    target.
    """

    def __init__(self, user_id: Optional[int] = None, repo_path: Optional[str] = None):
        # repo_path is kept for logging + future container-path translation.
        # In container mode it will be a host path like
        # "/workspaces/user_42/website/<proj>" that needs translating to
        # "/workspace/website/<proj>" inside the container.
        self.user_id = user_id
        self.repo_path = repo_path or ""
        self.mode = EXECUTION_MODE

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def wrap_command(
        self,
        command: List[str],
        *,
        run_as_root: bool = False,
    ) -> List[str]:
        """Wrap a base command for the active execution mode.

        This is the pure function form — useful when the caller needs to log
        the effective command before spawning (as claude_code_agent does).

        Local mode:
            If the current process is root and the command isn't explicitly
            requested as root, wraps with `sudo -E -H -u <LOCAL_RUN_AS_USER>`.
            Identical to claude_code_agent.py:806-808 today.

        Container mode (stub until Phase 4):
            Returns the command unchanged — Phase 4 will return the
            `docker exec -u 1001:1001 ...` form. Raising here would be wrong
            because Phase 1 callers may run before any container exists.

        Args:
            command: The base command list, e.g. ["claude", "-p", "...", ...].
            run_as_root: If True, skip the sudo wrapping even in local mode
                (matches the legacy "is_root" gate being inverted).
        """
        if self.mode == "container":
            # Phase 4 will implement: ContainerManager(self.user_id).wrap_exec(command, cwd)
            # For Phase 1 we never reach here because EXECUTION_MODE defaults to "local".
            # If someone flips the flag before Phase 4 ships, fail loudly rather than
            # silently running on host.
            raise NotImplementedError(
                "EXECUTION_MODE=container is not implemented until Phase 4. "
                "Set EXECUTION_MODE=local (or unset it) to use today's behavior."
            )

        # Local mode — mirror claude_code_agent.py:802-808 exactly.
        is_root = os.geteuid() == 0 if hasattr(os, "geteuid") else False
        if is_root and not run_as_root:
            logger.debug(
                "RuntimeManager local mode: wrapping with sudo -E -H -u %s",
                LOCAL_RUN_AS_USER,
            )
            return ["sudo", "-E", "-H", "-u", LOCAL_RUN_AS_USER, *command]
        return list(command)

    async def exec_subprocess_stream(
        self,
        command: List[str],
        *,
        cwd: str,
        env: Dict[str, str],
        stdout_limit: int = 10 * 1024 * 1024,
        run_as_root: bool = False,
    ) -> RuntimeSpawnResult:
        """Async spawn with stdout/stderr pipes — the Claude Code path.

        This is the spawn half of claude_code_agent._execute_query's
        `asyncio.create_subprocess_exec(...)` call. The caller still reads
        `result.process.stdout` line by line and parses stream-json — that
        parsing logic does NOT move here.

        Local mode: spawns the command directly (after sudo wrapping if root).
            Identical behavior to today.
        Container mode: not implemented until Phase 4.

        Args:
            command: Base command (e.g. ["claude", "-p", prompt, ...]).
            cwd: Working directory (host path).
            env: Full environment dict (already merged with settings/env).
            stdout_limit: asyncio pipe line limit (10MB default matches
                claude_code_agent.py:832 to handle base64 screenshots).
            run_as_root: Skip sudo wrapping even if EUID is 0.
        """
        effective = self.wrap_command(command, run_as_root=run_as_root)

        if self.mode == "container":
            # Phase 4 will hand off to ContainerManager.exec_stream here.
            raise NotImplementedError(
                "EXECUTION_MODE=container stream path is Phase 4 work."
            )

        logger.debug(
            "RuntimeManager.exec_subprocess_stream local mode: cwd=%s cmd=%s",
            cwd,
            " ".join(effective[:6]) + (" ..." if len(effective) > 6 else ""),
        )

        process = await asyncio.create_subprocess_exec(
            *effective,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
            limit=stdout_limit,
            start_new_session=True,  # New process group so we can kill entire tree
        )
        return RuntimeSpawnResult(
            process=process,
            requested_cwd=str(cwd),
            effective_command=effective,
        )

    def exec_subprocess(
        self,
        command: List[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        capture_output: bool = True,
        text: bool = True,
        check: bool = False,
        run_as_root: bool = False,
    ) -> subprocess.CompletedProcess:
        """Sync subprocess.run equivalent.

        Used by Phase 5 (build: npm/pip) and any future sync call site.
        Today nothing calls this — it exists so Phase 5 has a ready-made
        abstraction to route buildpublish.py and infrastructure_manager.py
        build calls through.

        Local mode: standard subprocess.run after sudo wrapping.
        Container mode: Phase 5 will hand off to ContainerManager.exec.
        """
        effective = self.wrap_command(command, run_as_root=run_as_root)

        if self.mode == "container":
            raise NotImplementedError(
                "EXECUTION_MODE=container sync path is Phase 5 work."
            )

        return subprocess.run(
            effective,
            cwd=cwd,
            env=env,
            timeout=timeout,
            capture_output=capture_output,
            text=text,
            check=check,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Diagnostics
    # ─────────────────────────────────────────────────────────────────────

    def describe(self) -> Dict[str, Any]:
        """Human-readable description for logging / the monitoring dashboard."""
        return {
            "mode": self.mode,
            "user_id": self.user_id,
            "repo_path": self.repo_path,
            "local_run_as_user": LOCAL_RUN_AS_USER if self.mode == "local" else None,
        }
