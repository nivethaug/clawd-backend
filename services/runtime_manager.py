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

ProjectRuntimeManager absorbs that fork in one place.

API
---
- `exec_subprocess(...)`        → sync subprocess.run equivalent (Phase 5)
- `exec_subprocess_stream(...)` → async subprocess stream equivalent (for Claude)
- `wrap_command(...)`           → pure function form, returns effective command

Both build the right command (local `sudo -u dreampilot` vs container
`docker exec -u 1001:1001`) based on `EXECUTION_MODE` and `user_id`, then hand
off to `subprocess` or `ContainerManager` respectively.

Environment handling (security-critical)
-----------------------------------------
In LOCAL mode, the caller's full `os.environ.copy()` is passed to the subprocess
(today's behavior — host inherits everything).

In CONTAINER mode, only an allowlisted set of env vars is forwarded. Forwarding
the full host env would leak DB credentials, Hostinger/GitHub tokens, and the
DREAMAGENT backend's own secrets into the user's container — exactly what the
isolation layer exists to prevent. The allowlist contains only what Claude +
builds need: provider keys, model config, and PATH.

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


# ─────────────────────────────────────────────────────────────────────
# Container env allowlist (security-critical)
# ─────────────────────────────────────────────────────────────────────
# In container mode, ONLY these env vars are forwarded from the host into the
# container. The container's claude.settings.json already pins ANTHROPIC_BASE_URL
# to host.docker.internal:7861 (the wrapper-v2 proxy). Anything not in this set
# is dropped — protecting DB_PASSWORD, LEMONSQUEEZY_WEBHOOK_SECRET, etc.
#
# To add a new forwarded env var (e.g. a new provider key), add its name here.
# Never add secrets that aren't meant to be visible inside the user's workspace.
_CONTAINER_ENV_ALLOWLIST = frozenset({
    # Anthropic / Claude routing (proxy URL set in settings.json, but token needed)
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    # OpenRouter (wrapper-v2 may use this as the upstream provider)
    "OPENROUTER_API_KEY",
    # Z.AI (zai-mcp-server injected by Claude's settings.json)
    "ZAI_API_KEY",
    "Z_AI_API_KEY",
    # PATH must be present so claude/node/npm/pip resolve inside the container
    "PATH",
    # Home directory (some Node tools consult $HOME for caches)
    "HOME",
})


def _filter_env_for_container(env: Dict[str, str]) -> Dict[str, str]:
    """Return only the allowlisted env vars (container mode).

    This is the security chokepoint between host env and container env. If a
    caller tries to pass DB creds or other secrets, they will be dropped here.
    """
    return {k: v for k, v in env.items() if k in _CONTAINER_ENV_ALLOWLIST}


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
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        run_as_root: bool = False,
    ) -> List[str]:
        """Wrap a base command for the active execution mode.

        This is the pure function form — useful when the caller needs to log
        the effective command before spawning (as claude_code_agent does).

        Local mode:
            If the current process is root and the command isn't explicitly
            requested as root, wraps with `sudo -E -H -u <LOCAL_RUN_AS_USER>`.
            Identical to claude_code_agent.py:806-808 today. `cwd`/`env` are
            ignored here — they go to the subprocess directly at spawn time.

        Container mode (Phase 4):
            Returns the full `docker exec -u 1001:1001 -w <container-path>
            -e KEY=val ... dreamagent-user-<uid> <command>` list. Path
            translation + env allowlist filtering happen here. Raises if
            user_id is not set.

        Args:
            command: The base command list, e.g. ["claude", "-p", "...", ...].
            cwd: Required in container mode (for path translation). Ignored
                in local mode.
            env: Environment dict. In container mode, filtered to the
                allowlist (see _CONTAINER_ENV_ALLOWLIST). Ignored in local
                mode (caller passes full env to subprocess separately).
            run_as_root: If True, skip the sudo wrapping even in local mode
                (matches the legacy "is_root" gate being inverted).
        """
        if self.mode == "container":
            if self.user_id is None or self.user_id <= 0:
                raise ValueError(
                    "EXECUTION_MODE=container requires a valid user_id on "
                    f"ProjectRuntimeManager (got {self.user_id!r})"
                )
            if cwd is None and self.repo_path:
                cwd = self.repo_path
            if cwd is None:
                raise ValueError(
                    "EXECUTION_MODE=container requires cwd (or repo_path on the manager)"
                )
            # Defer import so the module loads even if container_manager has issues
            # during dev (and to avoid circular imports at module load time).
            from services.container_manager import ContainerManager
            cm = ContainerManager(self.user_id)
            filtered_env = _filter_env_for_container(env or {})
            return cm.wrap_exec(command, cwd=cwd, env=filtered_env)

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

        Container mode (Phase 4): ensures the user's container is running,
            then spawns `docker exec ... claude ...` as the effective command.
            stdout streaming passes through `docker exec`'s pipe unchanged.

        Args:
            command: Base command (e.g. ["claude", "-p", prompt, ...]).
            cwd: Working directory (host path).
            env: Full environment dict (already merged with settings/env).
                In container mode, this gets filtered to the allowlist.
            stdout_limit: asyncio pipe line limit (10MB default matches
                claude_code_agent.py:832 to handle base64 screenshots).
            run_as_root: Skip sudo wrapping even if EUID is 0.
        """
        if self.mode == "container":
            if self.user_id is None or self.user_id <= 0:
                raise ValueError(
                    "EXECUTION_MODE=container requires user_id on ProjectRuntimeManager"
                )
            from services.container_manager import ContainerManager
            cm = ContainerManager(self.user_id)
            # Make sure the container exists + is running before exec.
            # Idempotent — cheap if already up.
            cm.ensure_container()
            # Filter env to allowlist before constructing the docker exec command.
            filtered_env = _filter_env_for_container(env)
            effective = cm.wrap_exec(command, cwd=cwd, env=filtered_env)
            logger.debug(
                "RuntimeManager.exec_subprocess_stream container mode: container=%s cmd=%s",
                cm.container_name,
                " ".join(effective[:6]) + (" ..." if len(effective) > 6 else ""),
            )
            process = await asyncio.create_subprocess_exec(
                *effective,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=stdout_limit,
                start_new_session=True,
            )
            return RuntimeSpawnResult(
                process=process,
                requested_cwd=str(cwd),
                effective_command=effective,
            )

        # Local mode — identical to pre-Phase-4 behavior.
        effective = self.wrap_command(command, run_as_root=run_as_root)
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
        Container mode (Phase 5): builds the docker exec command (with env
        filtering + path translation) and runs it. The container must exist
        before this is called — callers should ensure_container first.
        """
        # In container mode, wrap_command returns the full docker exec list
        # (no separate cwd/env on subprocess.run — they're baked into -w/-e).
        if self.mode == "container":
            from services.container_manager import ContainerManager
            cm = ContainerManager(self.user_id)
            cm.ensure_container()
            filtered_env = _filter_env_for_container(env or {})
            full_cmd = cm.wrap_exec(command, cwd=cwd or self.repo_path, env=filtered_env)
            return subprocess.run(
                full_cmd,
                timeout=timeout,
                capture_output=capture_output,
                text=text,
                check=check,
            )

        # Local mode
        effective = self.wrap_command(command, run_as_root=run_as_root)
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
