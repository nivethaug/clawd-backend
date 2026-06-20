"""
GitHub Export Service

Creates a clean, filtered copy of a project and pushes it to the user's own
GitHub repository via the GitHub REST API (using the user's OAuth token).

Security guarantees:
  - Never copies `.env` files (only generates an empty `.env.example`)
  - Never copies DreamAgent internals: `agent/`, `llm/`, `project.json`,
    `changerule.md`, `git_workflow.py`, `logs/`, etc.
  - Never copies build artifacts: `node_modules/`, `dist/`, `build/`, `__pycache__/`
  - User-supplied OAuth token is only used in-memory (loaded from DB per-call)
"""

import logging
import os
import re
from typing import Optional

import httpx

# Shared filtering + artifact logic lives in export_service (single source of
# truth). We re-export the public functions here so existing callers that do
# ``github_export_service.prepare_export_directory(...)`` keep working without
# any changes to app.py.
from export_service import (  # noqa: F401  (re-exported for backward compat)
    EXPORT_EXCLUDE_DIRS,
    EXPORT_EXCLUDE_FILES,
    EXPORT_EXCLUDE_GLOBS,
    MAX_FILE_BYTES,
    _path_is_excluded,
    generate_env_example,
    generate_gitignore,
    generate_readme,
    prepare_export_directory,
    cleanup_export_directory,
)

logger = logging.getLogger(__name__)


# ============================================================================
# GITHUB API: REPO CREATION + FILE PUSH
# ============================================================================

GITHUB_API_BASE = "https://api.github.com"


def _gh_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def create_repo_and_push(
    access_token: str,
    repo_name: str,
    private: bool,
    export_dir: str,
    description: str = "Project exported from DreamAgent",
) -> dict:
    """
    Create a new GitHub repository for the user and push the prepared files.

    Uses the GitHub REST API:
      1. POST /user/repos to create the repo (auto-initializes with empty main branch).
      2. Walks export_dir, creates blobs for each file.
      3. Builds a tree referencing all blobs.
      4. Creates a commit on top of the repo's current head (or as the first commit).
      5. Updates the refs/heads/main reference.

    Args:
        access_token: User's GitHub OAuth token.
        repo_name: Repository name (must be valid GitHub repo name).
        private: Whether the repo should be private.
        export_dir: Path returned by prepare_export_directory().
        description: Optional repo description.

    Returns:
        {'repo_url': str, 'repo_full_name': str, 'commit_sha': str, 'file_count': int}

    Raises:
        RuntimeError: on any GitHub API failure (status, conflict, network).
    """
    headers = _gh_headers(access_token)

    with httpx.Client(timeout=60.0, headers=headers) as client:
        # 1. Create the repository
        create_resp = client.post(
            f"{GITHUB_API_BASE}/user/repos",
            json={
                "name": repo_name,
                "description": description,
                "private": private,
                "auto_init": True,
                "gitignore_template": "Node",
            },
        )
        if create_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"GitHub create repo failed: HTTP {create_resp.status_code} "
                f"{create_resp.text}"
            )
        repo = create_resp.json()
        repo_full_name = repo["full_name"]
        repo_url = repo["html_url"]
        owner = repo["owner"]["login"]

        # 2. Collect files and create blobs
        blobs: List[Tuple[str, str]] = []  # (path, blob_sha)
        file_count = 0

        for root, _dirs, files in os.walk(export_dir):
            for fname in files:
                src = os.path.join(root, fname)
                rel = os.path.relpath(src, export_dir).replace("\\", "/")
                try:
                    with open(src, "rb") as f:
                        content_bytes = f.read()
                except OSError as e:
                    logger.warning("Skipping %s during push: %s", rel, e)
                    continue

                blob_resp = client.post(
                    f"{GITHUB_API_BASE}/repos/{repo_full_name}/git/blobs",
                    json={
                        "content": content_bytes.decode("utf-8", errors="replace")
                        if len(content_bytes) < 100 * 1024 * 1024
                        else "",
                        "encoding": "utf-8",
                    },
                )
                if blob_resp.status_code not in (200, 201):
                    raise RuntimeError(
                        f"Blob create failed for {rel}: HTTP "
                        f"{blob_resp.status_code} {blob_resp.text}"
                    )
                blob_sha = blob_resp.json()["sha"]
                blobs.append((rel, blob_sha))
                file_count += 1

        if not blobs:
            raise RuntimeError("No files to push after filtering")

        # 3. Build a tree referencing all the blobs
        tree_entries = [
            {"path": path, "mode": "100644", "type": "blob", "sha": sha}
            for path, sha in blobs
        ]
        tree_resp = client.post(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/git/trees",
            json={"base_tree": None, "tree": tree_entries},
        )
        if tree_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Tree create failed: HTTP {tree_resp.status_code} {tree_resp.text}"
            )
        tree_sha = tree_resp.json()["sha"]

        # 4. Determine parent commit (the auto_init created an initial commit on main)
        parent_sha: Optional[str] = None
        ref_resp = client.get(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/git/ref/heads/main"
        )
        if ref_resp.status_code == 200:
            parent_sha = ref_resp.json()["object"]["sha"]
        else:
            # Some repos default to 'master' — try that
            ref2 = client.get(
                f"{GITHUB_API_BASE}/repos/{repo_full_name}/git/ref/heads/master"
            )
            if ref2.status_code == 200:
                parent_sha = ref2.json()["object"]["sha"]
                # Rename master -> main
                client.post(
                    f"{GITHUB_API_BASE}/repos/{repo_full_name}/git/refs",
                    json={"ref": "refs/heads/main", "sha": parent_sha},
                )

        # 5. Create commit
        commit_json = {
            "message": "Initial project export from DreamAgent",
            "tree": tree_sha,
            "parents": [parent_sha] if parent_sha else [],
        }
        commit_resp = client.post(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/git/commits",
            json=commit_json,
        )
        if commit_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Commit create failed: HTTP {commit_resp.status_code} "
                f"{commit_resp.text}"
            )
        commit_sha = commit_resp.json()["sha"]

        # 6. Force-update main to point at our commit
        patch_resp = client.patch(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/git/refs/heads/main",
            json={"sha": commit_sha, "force": True},
        )
        if patch_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Ref update failed: HTTP {patch_resp.status_code} {patch_resp.text}"
            )

    return {
        "repo_url": repo_url,
        "repo_full_name": repo_full_name,
        "commit_sha": commit_sha,
        "file_count": file_count,
    }


def sanitize_repo_name(name: str) -> str:
    """
    Convert a project name into a valid GitHub repository name.
    GitHub rules: alphanumeric, hyphens, underscores, periods; max 100 chars.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "-", name).strip("-_.")
    if not cleaned:
        cleaned = "dreamagent-project"
    return cleaned[:100]
