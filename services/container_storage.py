"""
ContainerStorage — host/container path translation + allowlist primitives.

The single source of truth for "where does this user's project live?" Both the
legacy host layout and the new container layout resolve through this module.

Two layouts are supported, switched by EXECUTION_MODE:

  EXECUTION_MODE=local (default, today's behavior):
    host path      = /root/dreampilot/projects/{type_folder}/{project_dir}
    container path = (unused — nothing runs in a container)

  EXECUTION_MODE=container (Phase 2 onward):
    host path      = /workspaces/user_{user_id}/{type_folder}/{project_dir}
    container path = /workspace/{type_folder}/{project_dir}
                     (the host path's /workspaces/user_{user_id} prefix is
                      replaced with /workspace, matching the bind-mount target)

The container path is returned today but only consumed starting in Phase 4
(when Claude runs inside a container). The host path is what every file
operation, nginx serve, build, and DB record uses.

Why centralize path construction
--------------------------------
- Path-traversal guards in 3 files (project_manager, context_injector, app.py)
  must agree on the same allowed root. Without a shared source, one guard
  could accept what another rejects.
- Phase 4 needs to translate host paths to in-container paths. Doing this in
  one place (instead of ad-hoc replace() across 7 files) keeps the swap safe.
- Future layouts (NFS, named volumes) only require swapping this module's
  internals; every caller stays unchanged.

Backward compatibility
----------------------
In EXECUTION_MODE=local, every method returns the exact same path string the
caller would have produced inline before this refactor. No behavior change.
"""

from __future__ import annotations

import os
import posixpath
import logging
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

# NOTE on posixpath: every path this module constructs targets the Linux worker
# VPS (/root/dreampilot/projects, /workspaces/user_<id>, /workspace). Using
# posixpath.join (forward slashes) instead of os.path.join keeps the output
# consistent regardless of the dev platform running this code (Windows dev
# boxes would otherwise produce backslashes). On Linux posixpath == os.path.


# ─────────────────────────────────────────────────────────────────────
# Config (all env-overridable; defaults match today's hardcoded values)
# ─────────────────────────────────────────────────────────────────────

# Resolved once at module import, matching how runtime_manager reads EXECUTION_MODE.
EXECUTION_MODE: str = os.getenv("EXECUTION_MODE", "local").lower().strip()

# Legacy host layout (used when EXECUTION_MODE=local).
# Matches project_manager.py:14 BASE_PROJECTS_DIR and context_injector.py:17 PROJECT_BASE_PATH.
LEGACY_PROJECTS_ROOT: str = os.getenv("LEGACY_PROJECTS_ROOT", "/root/dreampilot/projects")

# Container host layout (used when EXECUTION_MODE=container).
# Matches container_manager.py WORKSPACE_ROOT.
WORKSPACE_ROOT: str = os.getenv("WORKSPACE_ROOT", "/workspaces")
WORKSPACE_USER_PREFIX: str = "user_"  # /workspaces/user_<id>

# Container in-container mount target. Matches container_manager.py CONTAINER_MOUNT_TARGET.
# host /workspaces/user_42/<rest>  →  container /workspace/<rest>
CONTAINER_MOUNT_TARGET: str = os.getenv("CONTAINER_MOUNT_TARGET", "/workspace")

# Website subfolder (the type_folder for type_id=1 / "website" projects).
# Most path-traversal guards today are scoped to website projects specifically.
WEBSITE_TYPE_FOLDER: str = "website"


# ─────────────────────────────────────────────────────────────────────
# Path construction
# ─────────────────────────────────────────────────────────────────────

def projects_root(user_id: Optional[int] = None) -> str:
    """Return the host root that holds project folders.

    local mode:        /root/dreampilot/projects         (user_id ignored — flat layout)
    container mode:    /workspaces/user_<id>             (per-user dir)

    Args:
        user_id: Required in container mode. Ignored in local mode.
    """
    if EXECUTION_MODE == "container":
        if user_id is None or user_id <= 0:
            raise ValueError(
                f"user_id is required in EXECUTION_MODE=container (got {user_id!r})"
            )
        return posixpath.join(WORKSPACE_ROOT, f"{WORKSPACE_USER_PREFIX}{user_id}")
    return LEGACY_PROJECTS_ROOT


def website_root(user_id: Optional[int] = None) -> str:
    """Return the host root of website-type projects.

    local mode:        /root/dreampilot/projects/website
    container mode:    /workspaces/user_<id>/website

    This is what the 3 path-traversal guards and buildpublish.py historically
    hard-coded as their allowed root.
    """
    return posixpath.join(projects_root(user_id), WEBSITE_TYPE_FOLDER)


def project_path(
    user_id: Optional[int],
    type_folder: str,
    project_dir: str,
) -> str:
    """Return the full host path for a specific project.

    local mode:        /root/dreampilot/projects/{type_folder}/{project_dir}
    container mode:    /workspaces/user_<id>/{type_folder}/{project_dir}

    Args:
        user_id: Owner. Required in container mode; ignored in local mode.
        type_folder: One of 'website', 'telegram', 'discord', 'scheduler', etc.
        project_dir: The per-project folder name (e.g. '1706_newnat_20260718_145142').
    """
    return posixpath.join(projects_root(user_id), type_folder, project_dir)


# ─────────────────────────────────────────────────────────────────────
# In-container translation (used from Phase 4 onward)
# ─────────────────────────────────────────────────────────────────────

def to_container_path(host_path: str) -> str:
    """Translate a host workspace path to its in-container equivalent.

    /workspaces/user_42/website/<proj>  →  /workspace/website/<proj>

    Paths outside /workspaces are returned unchanged (and logged) — they
    shouldn't be passed in container mode, but failing loudly on every such
    call would break Phase 4 development. Callers that need strict
    containment should use is_within_workspace() first.

    In EXECUTION_MODE=local this is a no-op (returns the input unchanged);
    nothing should call it, but the safety net is there.
    """
    if EXECUTION_MODE == "local":
        return host_path

    # container mode
    workspace_prefix = WORKSPACE_ROOT + "/"  # /workspaces/
    if host_path.startswith(workspace_prefix):
        # Strip /workspaces/user_<id>/ and prepend /workspace/
        remainder = host_path[len(workspace_prefix):]
        # remainder looks like "user_42/website/<proj>"
        slash_idx = remainder.find("/")
        if slash_idx == -1:
            # Path is exactly /workspaces/user_42 (no project subdir)
            return CONTAINER_MOUNT_TARGET
        rest = remainder[slash_idx + 1:]  # website/<proj>
        return posixpath.join(CONTAINER_MOUNT_TARGET, rest)

    # Outside /workspaces — return unchanged but warn. This catches bugs where
    # a host path (e.g. /etc/nginx/...) gets passed to a function expecting a
    # workspace path.
    logger.warning(
        "to_container_path: path %r is not under workspace root %r — returning unchanged",
        host_path,
        WORKSPACE_ROOT,
    )
    return host_path


# ─────────────────────────────────────────────────────────────────────
# Path-traversal guards (replaces inline startswith() checks)
# ─────────────────────────────────────────────────────────────────────

def _posix_normalized(p: str) -> str:
    """Normalize a POSIX path string lexically (no filesystem access).

    Equivalent to os.path.realpath ONLY when the path has no symlinks — which
    is true for the worker project tree (flat dirs, no symlinks). Using lexical
    normalization keeps the check consistent across dev platforms (Windows
    os.path.realpath would prepend a drive letter and break the comparison).

    On Linux production this matches what the original `os.path.realpath(...)`
    check produced for the worker's actual filesystem layout.
    """
    if not p:
        return ""
    # Collapse ../, ./, and duplicate slashes lexically.
    return posixpath.normpath(p)


def is_within_projects_root(path: str, user_id: Optional[int] = None) -> bool:
    """True if `path` is within the projects root (type-agnostic).

    Used for general file-operations guards. In local mode this accepts any
    project under /root/dreampilot/projects/<any_type>/...; in container mode
    it accepts only the calling user's workspace.
    """
    if not path:
        return False
    try:
        root = _posix_normalized(projects_root(user_id))
        real = _posix_normalized(path)
        return real == root or real.startswith(root + "/")
    except (OSError, ValueError):
        return False


def is_within_website_root(path: str, user_id: Optional[int] = None) -> bool:
    """True if `path` is within the website projects root.

    This is the strict guard used by context_injector.py and app.py:3209
    historically. Keeps the same scope (website projects only) so existing
    rejections don't change.
    """
    if not path:
        return False
    try:
        root = _posix_normalized(website_root(user_id))
        real = _posix_normalized(path)
        return real == root or real.startswith(root + "/")
    except (OSError, ValueError):
        return False


# ─────────────────────────────────────────────────────────────────────
# Diagnostics
# ─────────────────────────────────────────────────────────────────────

def describe() -> dict:
    """Return the active layout config — for logging + the monitoring dashboard."""
    return {
        "execution_mode": EXECUTION_MODE,
        "legacy_projects_root": LEGACY_PROJECTS_ROOT,
        "workspace_root": WORKSPACE_ROOT,
        "container_mount_target": CONTAINER_MOUNT_TARGET,
        "website_type_folder": WEBSITE_TYPE_FOLDER,
    }
