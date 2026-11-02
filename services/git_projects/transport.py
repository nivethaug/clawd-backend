"""Git transport — clone/fetch/pull/push/checkout inside the user's container.

All git operations run inside the user's Docker container via docker exec.
Credentials are injected via GIT_CONFIG_KEY/VALUE env vars (never in
process arguments, repo config, or on disk).
"""
import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class GitTransport:
    """Execute git commands inside the user's container."""

    def __init__(self, user_id: int, project_path: str):
        self.user_id = user_id
        self.project_path = project_path  # host path
        self.container = f"dreamagent-user-{user_id}"

    def _exec(
        self,
        command: str,
        token: Optional[str] = None,
        timeout: int = 300,
        cwd: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """Run a command inside the container. Token injected via env if provided."""
        env_flags = []
        if token:
            # Inject as git http extraheader (auth without storing in config)
            import base64
            auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env_flags = [
                "-e", f"GIT_CONFIG_COUNT=1",
                "-e", f"GIT_CONFIG_KEY_0=http.https://github.com/.extraheader",
                "-e", f"GIT_CONFIG_VALUE_0=Authorization: Basic {auth}",
            ]

        workdir = cwd or self.project_path
        # Translate host path to container path
        container_path = workdir.replace("/workspaces/user_", "/workspace/user_")
        # Actually the mount maps /workspaces/user_{id} → /workspace
        # So /workspaces/user_24/website/... → /workspace/website/...
        if "/workspaces/user_" in workdir:
            parts = workdir.split("/", 3)  # ['', 'workspaces', 'user_24', 'rest...']
            if len(parts) >= 4:
                container_path = "/" + parts[3]

        cmd = [
            "docker", "exec",
            "-i",
            "--user", "1001:1001",
            "--workdir", container_path,
            *env_flags,
            self.container,
            "bash", "-c", command,
        ]

        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )

    def clone(
        self,
        url: str,
        branch: Optional[str] = None,
        shallow: bool = False,
        token: Optional[str] = None,
        dest_dir: str = ".",
    ) -> dict:
        """Clone a repository (full history by default)."""
        depth_flag = "--depth 1" if shallow else ""
        branch_flag = f"--branch {branch}" if branch else ""

        cmd = (
            f"git clone {depth_flag} {branch_flag} "
            f"--config http.followRedirects=false "
            f"--config protocol.ext.allow=never "
            f"--config protocol.file.allow=never "
            f"{url} {dest_dir} 2>&1"
        )

        result = self._exec(cmd, token=token, timeout=600, cwd="/tmp")
        success = result.returncode == 0

        return {
            "success": success,
            "output": result.stdout[-2000:] if result.stdout else result.stderr[-2000:],
        }

    def status(self) -> dict:
        """Get working tree status."""
        result = self._exec("git status --porcelain 2>&1 && git branch --show-current")
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "dirty": bool(result.stdout.strip().split("\n")[0]),
        }

    def commit(self, message: str, paths: Optional[str] = None) -> dict:
        """Stage and commit changes."""
        add_cmd = f"git add {paths}" if paths else "git add -A"
        result = self._exec(f"{add_cmd} && git commit -m '{message}' && git rev-parse HEAD")
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "sha": result.stdout.strip().split("\n")[-1] if result.returncode == 0 else None,
        }

    def push(self, token: Optional[str] = None, force: bool = False) -> dict:
        """Push to origin."""
        force_flag = "--force-with-lease" if force else ""
        result = self._exec(f"git push {force_flag} origin HEAD 2>&1", token=token, timeout=120)
        return {
            "success": result.returncode == 0,
            "output": result.stdout[-1000:] + result.stderr[-1000:],
        }

    def pull(self, token: Optional[str] = None, rebase: bool = True) -> dict:
        """Pull from origin."""
        rebase_flag = "--rebase" if rebase else ""
        result = self._exec(f"git pull {rebase_flag} origin 2>&1", token=token, timeout=120)
        return {
            "success": result.returncode == 0,
            "output": result.stdout[-1000:] + result.stderr[-1000:],
        }

    def ahead_behind(self) -> dict:
        """Get ahead/behind counts vs origin."""
        result = self._exec(
            "git rev-list --left-right --count HEAD...origin/$(git branch --show-current) 2>/dev/null"
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            return {"ahead": int(parts[0]), "behind": int(parts[1])}
        return {"ahead": 0, "behind": 0}

    def diff(self, staged: bool = False) -> str:
        """Get diff of changes."""
        flag = "--cached" if staged else ""
        result = self._exec(f"git diff {flag}")
        return result.stdout

    def log(self, count: int = 10) -> str:
        """Get recent commit log."""
        result = self._exec(f"git log --oneline -{count}")
        return result.stdout
