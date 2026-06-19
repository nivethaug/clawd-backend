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

import fnmatch
import logging
import os
import shutil
import tempfile
import uuid
from typing import List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# Maximum file size copied into the export (50 MB). Larger files are skipped
# to keep the GitHub tree API upload efficient.
MAX_FILE_BYTES = 50 * 1024 * 1024


# ============================================================================
# EXCLUSION RULES
# ============================================================================

# Universal exclusions applied to ALL project types.
# Patterns are matched against relative path components and basenames.
EXPORT_EXCLUDE_DIRS = {
    "agent",
    "llm",
    "logs",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".vscode",
    ".idea",
    ".git",
    ".venv",
    "venv",
    "env",
    ".cache",
}

EXPORT_EXCLUDE_FILES = {
    "project.json",
    "changerule.md",
    "git_workflow.py",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "ecosystem.config.json",
    "ecosystem.backend.json",
    "ecosystem.scheduler.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "package-lock.json",
    ".DS_Store",
    "npm-debug.log",
    "yarn-error.log",
}

EXPORT_EXCLUDE_GLOBS = [
    "*.log",
    "*.pid",
    "*.pyc",
    "*.pyo",
    ".env.*",  # any .env.* variant (but we explicitly keep .env.example)
]


def _path_is_excluded(rel_path: str) -> bool:
    """
    Return True if a relative path should be excluded from the export.

    Checks directory components, exact filenames, and glob patterns.
    """
    parts = rel_path.replace("\\", "/").split("/")
    for part in parts:
        if part in EXPORT_EXCLUDE_DIRS:
            return True
    basename = parts[-1] if parts else rel_path
    if basename in EXPORT_EXCLUDE_FILES:
        return True
    # Always allow the generated .env.example even though .env.* is excluded
    if basename == ".env.example":
        return False
    for pattern in EXPORT_EXCLUDE_GLOBS:
        if fnmatch.fnmatch(basename, pattern):
            return True
    return False


# ============================================================================
# ARTIFACT GENERATION
# ============================================================================

UNIVERSAL_GITIGNORE = """\
# Dependencies
node_modules/
.pnp
.pnp.js

# Build output
dist/
build/
*.tsbuildinfo

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
.venv/
*.egg-info/
.pytest_cache/

# Environment variables (never commit real secrets)
.env
.env.local
.env.*.local

# Logs
logs/
*.log
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Editor / OS
.vscode/
.idea/
.DS_Store
Thumbs.db

# Process management
ecosystem.config.json
*.pid

# DreamAgent internals (not part of your project source)
agent/
llm/
project.json
"""

TYPE_GITIGNORE_EXTRA = {
    1: """\
# Website (Vite + React)
.vite/
coverage/
""",  # website
    2: "",  # telegram
    3: "",  # discord
    4: "",  # trading
    5: "",  # scheduler
    6: "",  # custom
}


def generate_gitignore(type_id: int) -> str:
    """Build the .gitignore content for the given project type."""
    extra = TYPE_GITIGNORE_EXTRA.get(type_id, "")
    return UNIVERSAL_GITIGNORE + extra


def generate_env_example(project_path: str, type_id: int) -> str:
    """
    Generate a .env.example with keys from the project's .env file but
    with all values stripped (no secrets ever leak).

    Falls back to type-specific defaults if no .env is found.
    """
    # Map type_id -> subdirectory containing .env (matches env_manager.ENV_SUBDIR_MAP)
    env_subdir_map = {1: "backend", 2: "telegram", 3: "discord", 5: "scheduler"}
    subdir = env_subdir_map.get(type_id)

    keys: List[str] = []
    if subdir:
        env_path = os.path.join(project_path, subdir, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        stripped = line.strip()
                        if not stripped or stripped.startswith("#"):
                            continue
                        if "=" not in stripped:
                            continue
                        key = stripped.partition("=")[0].strip()
                        if key:
                            keys.append(key)
            except Exception as e:
                logger.warning("Failed to read .env at %s: %s", env_path, e)

    # Default placeholder keys if none found
    if not keys:
        defaults = {
            1: ["PORT", "DATABASE_URL", "VITE_API_URL"],
            2: ["TELEGRAM_BOT_TOKEN", "WEBHOOK_URL"],
            3: ["DISCORD_BOT_TOKEN"],
            4: ["EXCHANGE_API_KEY", "EXCHANGE_API_SECRET"],
            5: ["CRON_SCHEDULE", "WEBHOOK_URL"],
        }
        keys = defaults.get(type_id, ["PORT"])

    lines = ["# Environment variables. Fill these in and rename to .env", ""]
    for k in keys:
        lines.append(f"{k}=")
    return "\n".join(lines) + "\n"


def _readme_for_website(name: str) -> str:
    return f"""# {name}

A website project built with DreamAgent.

## Structure

- `frontend/` - React + Vite frontend
- `backend/` - FastAPI backend
- `database/` - Database schema and migrations

## Prerequisites

- Node.js 18+
- Python 3.10+
- PostgreSQL (or your preferred database)

## Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp ../.env.example .env  # Then fill in your values
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

See `.env.example` for required variables. Copy it to `.env` and fill in your values.

## License

This project was generated by DreamAgent.
"""


def _readme_for_python_bot(name: str, bot_kind: str) -> str:
    kind_title = bot_kind.title()
    return f"""# {name}

A {kind_title} bot project built with DreamAgent.

## Prerequisites

- Python 3.10+

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env  # Then fill in your {kind_title} token
python main.py
```

## Environment Variables

See `.env.example` for required variables. Copy it to `.env` and fill in your values.

## License

This project was generated by DreamAgent.
"""


def generate_readme(project_name: str, type_id: int) -> str:
    """Generate a type-appropriate README.md."""
    if type_id == 1:
        return _readme_for_website(project_name)
    if type_id == 2:
        return _readme_for_python_bot(project_name, "telegram")
    if type_id == 3:
        return _readme_for_python_bot(project_name, "discord")
    if type_id == 4:
        return _readme_for_python_bot(project_name, "trading")
    if type_id == 5:
        return _readme_for_python_bot(project_name, "scheduler")
    return f"# {project_name}\n\nA project built with DreamAgent.\n"


# ============================================================================
# DIRECTORY PREPARATION
# ============================================================================

def prepare_export_directory(
    project_path: str,
    type_id: int,
    project_name: str,
) -> str:
    """
    Create a clean filtered copy of the project in a temp directory,
    then write generated .gitignore, .env.example, and README.md.

    Args:
        project_path: Absolute path to the live project directory.
        type_id: Project type ID (1=website, 2=telegram, 3=discord, etc).
        project_name: Display name for the README header.

    Returns:
        Absolute path to the temp export directory.

    Raises:
        FileNotFoundError: if project_path does not exist.
    """
    if not os.path.isdir(project_path):
        raise FileNotFoundError(f"Project path does not exist: {project_path}")

    export_dir = os.path.join(
        tempfile.gettempdir(), f"dreamagent-export-{uuid.uuid4().hex}"
    )
    os.makedirs(export_dir, exist_ok=True)

    copied = 0
    skipped = 0
    for root, dirs, files in os.walk(project_path):
        # Filter directories in-place so os.walk doesn't descend into them
        dirs[:] = [d for d in dirs if d not in EXPORT_EXCLUDE_DIRS]

        for fname in files:
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, project_path)
            if _path_is_excluded(rel):
                skipped += 1
                continue
            try:
                if os.path.getsize(src) > MAX_FILE_BYTES:
                    skipped += 1
                    continue
            except OSError:
                skipped += 1
                continue

            dst = os.path.join(export_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1

    logger.info(
        "Export prep: copied %d files, skipped %d (type_id=%s)",
        copied, skipped, type_id,
    )

    # Write generated artifacts (overwrite any stale copies)
    with open(os.path.join(export_dir, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(generate_gitignore(type_id))
    with open(os.path.join(export_dir, ".env.example"), "w", encoding="utf-8") as f:
        f.write(generate_env_example(project_path, type_id))
    with open(os.path.join(export_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(generate_readme(project_name, type_id))

    return export_dir


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


def cleanup_export_directory(export_dir: str) -> None:
    """Remove a temp export directory created by prepare_export_directory."""
    try:
        shutil.rmtree(export_dir, ignore_errors=True)
    except Exception as e:
        logger.warning("Failed to clean up export dir %s: %s", export_dir, e)


def sanitize_repo_name(name: str) -> str:
    """
    Convert a project name into a valid GitHub repository name.
    GitHub rules: alphanumeric, hyphens, underscores, periods; max 100 chars.
    """
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "-", name).strip("-_.")
    if not cleaned:
        cleaned = "dreamagent-project"
    return cleaned[:100]
