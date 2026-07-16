#!/usr/bin/env python3
"""Release gate for critical security regressions.

This script checks the high-risk controls that must stay in place before a
public release. It is intentionally static and dependency-free so it can run in
CI, PM2 deploy hooks, or a developer shell.
"""

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT.parent / "muse-companion-app"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _git_ls_file(path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "ls-files", path],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def main() -> int:
    failures = []

    if _git_ls_file(".env.postgres") and (ROOT / ".env.postgres").exists():
        failures.append(".env.postgres is still tracked and present in the working tree")

    secret_patterns = [
        re.compile(r"StrongAdminPass123"),
        re.compile(r"355fc5e1f0d6078a8a9a56f684d551d803f92decf956d11ca7494f0f461b470a"),
        re.compile(r"ZAI_API_KEY\s*=\s*cffbf9", re.IGNORECASE),
    ]
    scanned_files = [
        ROOT / "app.py",
        ROOT / "database_postgres.py",
        ROOT / "fast_wrapper.py",
        ROOT / "openclaw_wrapper.py",
        ROOT / "image_handler.py",
        ROOT / "infrastructure_manager.py",
        ROOT / "services" / "project_creation_runs.py",
        ROOT / "services" / "discord" / "env_injector.py",
    ]
    for file_path in scanned_files:
        if not file_path.exists():
            continue
        content = _read(file_path)
        for pattern in secret_patterns:
            if pattern.search(content):
                failures.append(f"committed secret/default found in {file_path.relative_to(ROOT)}")
                break

    validate_router = _read(ROOT / "api" / "validate_router.py")
    validate_requirements = [
        "get_user_id_from_token",
        "_validate_safe_url",
        "allow_redirects=False",
        "Only GET and POST methods are allowed",
        "Private, local, reserved, or link-local targets are not allowed",
    ]
    for requirement in validate_requirements:
        if requirement not in validate_router:
            failures.append(f"api/validate_router.py missing {requirement}")

    scheduler_router = _read(ROOT / "api" / "scheduler_router.py")
    if "_require_project_owner" not in scheduler_router or "_require_job_owner" not in scheduler_router:
        failures.append("api/scheduler_router.py missing owner checks")
    if scheduler_router.count("authorization: Optional[str] = Header(None)") < 10:
        failures.append("api/scheduler_router.py does not auth-gate all scheduler endpoints")

    spa_server = _read(FRONTEND_ROOT / "spa_server.py")
    spa_requirements = [
        "ALLOWED_IMAGE_EXTENSIONS",
        "unquote",
        "relative_to",
        "/workspace/clawd-images",
    ]
    for requirement in spa_requirements:
        if requirement not in spa_server:
            failures.append(f"spa_server.py missing {requirement}")

    if failures:
        print("SECURITY RELEASE GATE FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("SECURITY RELEASE GATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
