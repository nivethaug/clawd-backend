"""
Export Service — Shared filtering and artifact generation for project exports.

This module is the SINGLE SOURCE OF TRUTH for:
  - Which files/dirs are excluded from exports (secrets, internals, build artifacts)
  - Generated artifacts (.gitignore, .env.example, README.md)
  - Preparing a clean filtered temp copy of a project

Both `github_export_service` (GitHub push) and the Download ZIP endpoint use
the exact same `prepare_export_directory()` so filtering logic is NEVER
duplicated.

Security guarantees:
  - Never copies `.env` files (only generates an empty `.env.example`)
  - Never copies DreamAgent internals: `agent/`, `llm/`, `project.json`,
    `changerule.md`, `git_workflow.py`, `logs/`, etc.
  - Never copies build artifacts: `node_modules/`, `dist/`, `build/`, `__pycache__/`
"""

import fnmatch
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from typing import List

logger = logging.getLogger(__name__)

# Maximum file size copied into the export (50 MB). Larger files are skipped
# to keep exports efficient and avoid bloating ZIPs / GitHub tree uploads.
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
    # "" = root .env (scheduler + agent families; matches env_manager)
    env_subdir_map = {1: "backend", 2: "telegram", 3: "discord", 5: "", 7: ""}
    subdir = env_subdir_map.get(type_id)

    keys: List[str] = []
    if subdir is not None:
        env_path = os.path.join(project_path, subdir, ".env") if subdir else os.path.join(project_path, ".env")
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

    This is the shared entry point used by BOTH GitHub Export and
    Download ZIP — guaranteeing identical filtering.

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
    symlink_skipped = 0
    for root, dirs, files in os.walk(project_path, followlinks=False):
        # Filter directories in-place so os.walk doesn't descend into them.
        # followlinks=False already prevents descending into symlinked dirs,
        # but drop any symlinked dir explicitly so it isn't recreated below.
        dirs[:] = [
            d for d in dirs
            if d not in EXPORT_EXCLUDE_DIRS and not os.path.islink(os.path.join(root, d))
        ]

        for fname in files:
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, project_path)

            # Reject symlinks: a symlinked file could point outside the project
            # (e.g. at a host secret) and shutil.copy2 would follow it.
            if os.path.islink(src):
                symlink_skipped += 1
                logger.warning(
                    "Export prep: skipped symlink outside project tree: %s", rel
                )
                continue

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
        "Export prep: copied %d files, skipped %d, symlink_skipped %d (type_id=%s)",
        copied, skipped, symlink_skipped, type_id,
    )

    # Write generated artifacts (overwrite any stale copies)
    with open(os.path.join(export_dir, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(generate_gitignore(type_id))
    with open(os.path.join(export_dir, ".env.example"), "w", encoding="utf-8") as f:
        f.write(generate_env_example(project_path, type_id))
    with open(os.path.join(export_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(generate_readme(project_name, type_id))

    return export_dir


def cleanup_export_directory(export_dir: str) -> None:
    """Remove a temp export directory created by prepare_export_directory."""
    try:
        shutil.rmtree(export_dir, ignore_errors=True)
    except Exception as e:
        logger.warning("Failed to clean up export dir %s: %s", export_dir, e)


# ============================================================================
# ZIP PACKAGING
# ============================================================================

def zip_directory(export_dir: str, zip_path: str) -> str:
    """
    Package a prepared export directory into a ZIP archive.

    Walks the already-filtered ``export_dir`` (output of
    :func:`prepare_export_directory`) and writes every file into
    ``zip_path`` using deflate compression. Files are stored with paths
    relative to ``export_dir`` (no leading directory prefix).

    Args:
        export_dir: Path returned by ``prepare_export_directory``.
        zip_path: Absolute path where the .zip should be written.

    Returns:
        The ``zip_path`` that was written.
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(export_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, export_dir)
                zf.write(fpath, arcname)
    logger.info("Created ZIP archive: %s", zip_path)
    return zip_path
