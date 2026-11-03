"""Git transport — clone/fetch/pull/push/checkout inside the user's container.

All git operations run inside the user's Docker container via docker exec.
Credentials are injected via a temporary GIT_ASKPASS script (never in
process arguments, repo config, or on persistent disk).
"""
import logging
import os
import shlex
import subprocess
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


class GitTransport:
    """Execute git commands inside the user's container."""

    def __init__(self, user_id: int, project_path: str):
        self.user_id = user_id
        self.project_path = project_path  # host path
        self.container = f"dreamagent-user-{user_id}"

    def _container_path(self) -> str:
        """Translate host project_path to container path using the platform helper."""
        from services.container_storage import to_container_path
        return to_container_path(self.project_path)

    def _exec(
        self,
        command: str,
        token: Optional[str] = None,
        timeout: int = 300,
    ) -> subprocess.CompletedProcess:
        """Run a command inside the container. Token via temporary askpass script."""
        env_flags = []
        try:
            if token:
                # Write askpass script INSIDE the container as user 1001
                # (docker cp preserves root ownership; --cap-drop ALL blocks chown)
                write = subprocess.run(
                    ["docker", "exec", "--user", "1001:1001", self.container,
                     "bash", "-c",
                     f"printf '#!/bin/bash\\necho {token}\\n' > /tmp/.gitask && chmod 700 /tmp/.gitask"],
                    capture_output=True, timeout=10,
                )
                if write.returncode == 0:
                    env_flags = ["-e", "GIT_ASKPASS=/tmp/.gitask", "-e", "GIT_TERMINAL_PROMPT=0"]

            cmd = [
                "docker", "exec", "-i",
                "--user", "1001:1001",
                "--workdir", self._container_path(),
                *env_flags,
                self.container,
                "bash", "-c", command,
            ]
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 124, "", f"Timeout after {timeout}s")
        except Exception as exc:
            return subprocess.CompletedProcess(cmd, 1, "", str(exc))
        finally:
            # Clean up askpass script inside the container
            subprocess.run(
                ["docker", "exec", self.container, "rm", "-f", "/tmp/.gitask"],
                capture_output=True, timeout=5,
                )

    @staticmethod
    def _safe_branch(branch: str) -> str:
        """Validate branch name (no shell metacharacters)."""
        import re
        if not re.match(r"^[A-Za-z0-9._/-]+$", branch or ""):
            raise ValueError(f"Invalid branch name: {branch!r}")
        return branch

    def clone(
        self,
        url: str,
        branch: Optional[str] = None,
        shallow: bool = False,
        token: Optional[str] = None,
    ) -> dict:
        """Clone a repository into the project path (full history by default)."""
        branch = self._safe_branch(branch or "main")
        depth = "--depth 1" if shallow else ""
        url_q = shlex.quote(url)
        branch_q = shlex.quote(branch)

        # Clear the destination (the platform's _create_project_folder leaves
        # README/git artifacts that make `git clone .` fail on non-empty dir)
        # Use find to handle hidden files properly, and log what's removed
        clear_result = self._exec(
            "pwd && ls -la && find . -mindepth 1 -delete 2>/dev/null; ls -la",
            timeout=30,
        )
        logger.info("[GIT-TRANSPORT] cleared %s: %s", self._container_path(),
                    clear_result.stdout[-300:] if clear_result.stdout else "no output")

        # Clone into the project directory
        cmd = (
            f"git clone {depth} --branch {branch_q} "
            f"--config http.followRedirects=false "
            f"{url_q} . 2>&1"
        )

        result = self._exec(cmd, token=token, timeout=600)
        return {
            "success": result.returncode == 0,
            "output": (result.stdout or result.stderr)[-2000:],
        }

    def status(self) -> dict:
        """Get working tree status (runs commands separately)."""
        porcelain = self._exec("git status --porcelain 2>&1")
        branch = self._exec("git branch --show-current 2>&1")
        dirty = bool(porcelain.stdout.strip()) if porcelain.returncode == 0 else False
        branch_name = branch.stdout.strip() if branch.returncode == 0 else "unknown"
        return {
            "success": porcelain.returncode == 0,
            "output": f"{porcelain.stdout}\n{branch_name}",
            "dirty": dirty,
            "branch": branch_name,
        }

    def commit(self, message: str, paths: Optional[str] = None) -> dict:
        """Stage and commit changes (message passed via file, not shell)."""
        # Write message to a temp file to avoid shell injection
        msg_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".msg", delete=False, prefix="gitmsg_",
        )
        msg_file.write(message[:500])
        msg_file.close()

        try:
            subprocess.run(
                ["docker", "cp", msg_file.name, f"{self.container}:/tmp/.gitmsg"],
                capture_output=True, timeout=10,
            )
            add_cmd = f"git add {shlex.quote(paths)}" if paths else "git add -A"
            result = self._exec(
                f"{add_cmd} && git commit -F /tmp/.gitmsg && git rev-parse HEAD && rm -f /tmp/.gitmsg"
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "sha": result.stdout.strip().split("\n")[-1] if result.returncode == 0 else None,
            }
        finally:
            os.unlink(msg_file.name)

    def push(self, token: Optional[str] = None, force: bool = False) -> dict:
        """Push to origin."""
        force_flag = "--force-with-lease" if force else ""
        result = self._exec(f"git push {force_flag} origin HEAD 2>&1", token=token, timeout=120)
        return {
            "success": result.returncode == 0,
            "output": (result.stdout or "")[-1000:] + (result.stderr or "")[-1000:],
        }

    def pull(self, token: Optional[str] = None, rebase: bool = True) -> dict:
        """Pull from origin."""
        rebase_flag = "--rebase" if rebase else ""
        result = self._exec(f"git pull {rebase_flag} origin 2>&1", token=token, timeout=120)
        return {
            "success": result.returncode == 0,
            "output": (result.stdout or "")[-1000:] + (result.stderr or "")[-1000:],
        }

    def ahead_behind(self) -> dict:
        result = self._exec(
            "git rev-list --left-right --count HEAD...origin/$(git branch --show-current) 2>/dev/null"
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                return {"ahead": int(parts[0]), "behind": int(parts[1])}
        return {"ahead": 0, "behind": 0}

    def diff(self, staged: bool = False) -> str:
        flag = "--cached" if staged else ""
        result = self._exec(f"git diff {flag}")
        return result.stdout

    def log(self, count: int = 10) -> str:
        result = self._exec(f"git log --oneline -{int(count)}")
        return result.stdout
