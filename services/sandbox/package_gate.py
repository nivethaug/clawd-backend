#!/usr/bin/env python3
"""
Package Gate (Layer 1A) — block oversized/unauthorized packages before pip
installs them into project sandboxes.

Enforced in two places:
  1. infrastructure_manager's pip install path (project build/self-heal)
  2. scripts/pip-gate.py — a pip shim prepended to PATH inside sandboxes,
     so even `Bash("pip install torch")` by an agent hits the same gate.

What it blocks:
  - BLOCKED_PACKAGES: multi-GB LLM/GPU runtimes. These belong on a GPU
    provider (RunPod) or behind an API — never inside a project sandbox.
    The error message tells the agent what to do instead, so it
    self-corrects (proven pattern).
  - Per-operation total size: PyPI JSON metadata wheel sizes summed over
    the requested packages (+ their pinned deps when cheaply knowable),
    capped at PROJECT_PIP_MAX_MB.

Env knobs (all optional; sane defaults):
  PIP_BLOCKED_PACKAGES   comma list appended to the built-in blocklist
  PROJECT_PIP_MAX_MB     max total download per install op (default 500)
  WHEELHOUSE_URL         extra index (Layer 1C shared wheelhouse);
                         never an allowlist-bypass — gate runs first.
"""

import json
import logging
import os
import re
from typing import List, Optional, Tuple

logger = logging.getLogger("services.sandbox.package_gate")

# Multi-GB LLM/GPU runtimes — the disk/killers this gate exists for.
# Wildcards allowed as "prefix-*".
DEFAULT_BLOCKED = {
    "torch", "torchvision", "torchaudio",
    "tensorflow", "tensorflow-gpu", "tensorflow-cpu", "keras",
    "transformers", "diffusers", "accelerate", "datasets",
    "jax", "jaxlib", "flax",
    "cupy", "cupy-cuda12x", "cupy-roll",
    "nvidia-*",                       # every nvidia-cublas/cudnn/... wheel
    "sentence-transformers", "stable-baselines3", "open3d",
    "llama-cpp-python", "ctranslate2", "onnxruntime-gpu",
}

_DEFAULT_MAX_MB = 500
_PYPI_JSON_TIMEOUT = 6.0


def blocked_packages() -> set:
    extra = os.getenv("PIP_BLOCKED_PACKAGES", "")
    merged = set(DEFAULT_BLOCKED)
    for name in extra.split(","):
        name = name.strip().lower()
        if name:
            merged.add(name)
    return merged


def max_install_mb() -> int:
    try:
        return max(50, int(os.getenv("PROJECT_PIP_MAX_MB", _DEFAULT_MAX_MB)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_MB


def is_blocked(name: str, blocklist: Optional[set] = None) -> Optional[str]:
    """Return the matching blocklist entry if `name` is blocked, else None."""
    blocklist = blocklist if blocklist is not None else blocked_packages()
    n = name.strip().lower()
    for entry in blocklist:
        if entry.endswith("*"):
            if n.startswith(entry[:-1]):
                return entry
        elif n == entry:
            return entry
    return None


# "pkg", "pkg>=1.0", "pkg[extra]==2.0 ; python_version<'3.12'", "git+...#egg=pkg"
_REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_EGG_RE = re.compile(r"#egg=([A-Za-z0-9][A-Za-z0-9._-]*)")


def requirement_name(req: str) -> Optional[str]:
    req = req.strip()
    if not req or req.startswith("#") or req.startswith("-"):
        return None
    if req.startswith(("git+", "http://", "https://")):
        m = _EGG_RE.search(req)
        return m.group(1).lower() if m else None
    m = _REQ_RE.match(req)
    return m.group(1).lower() if m else None


def _pypi_size_mb(name: str, version: Optional[str] = None) -> Optional[int]:
    """Best-effort wheel size from PyPI JSON metadata. None = unknown
    (network error / private package) — unknown is ALLOWED but counted as
    0; the blocklist + egress size cap (Layer 3) cover what this misses."""
    try:
        import httpx
        url = f"https://pypi.org/pypi/{name}/json"
        if version:
            url = f"https://pypi.org/pypi/{name}/{version}/json"
        r = httpx.get(url, timeout=_PYPI_JSON_TIMEOUT,
                      headers={"User-Agent": "dreamagent-package-gate/1.0"})
        if r.status_code != 200:
            return None
        data = r.json()
        releases = data.get("releases") or {}
        files = (data.get("urls")
                 or releases.get(version)
                 or releases.get(data.get("info", {}).get("version", ""))
                 or [])
        sizes = [f.get("size", 0) for f in files if isinstance(f, dict)]
        if not sizes:
            return None
        return max(sizes) // (1024 * 1024)  # largest file (worst case wheel)
    except Exception as e:  # noqa: BLE001 — gate must never crash installs
        logger.debug("package_gate pypi lookup failed for %s: %s", name, e)
        return None


def gate_requirements(requirements: List[str]) -> Tuple[bool, str]:
    """(allowed, message). Message is agent-actionable on failure."""
    blocklist = blocked_packages()
    cap = max_install_mb()

    names: List[str] = []
    for req in requirements:
        name = requirement_name(req)
        if name:
            names.append(name)

    for name in names:
        hit = is_blocked(name, blocklist)
        if hit:
            return False, (
                f"Package '{name}' is blocked (matched '{hit}'): LLM/GPU "
                "runtimes are not allowed in project sandboxes. Instead: "
                "(a) call LLMs via API (see the integrations/proxy docs in "
                "the build prompt), or (b) if the project genuinely needs "
                "GPU execution, use a GPU provider like RunPod via its API."
            )

    total_mb = 0
    oversized = []
    for name in names:
        size = _pypi_size_mb(name)
        if size is not None:
            total_mb += size
            if size > cap:
                oversized.append(f"{name} (~{size} MB)")
    if oversized:
        return False, (
            f"Package(s) exceed the per-package limit of {cap} MB: "
            + ", ".join(oversized)
            + ". Use lighter alternatives or an API instead."
        )
    if names and total_mb > cap:
        return False, (
            f"Total install size ~{total_mb} MB exceeds the {cap} MB limit "
            f"for this operation ({', '.join(names)}). Split the install or "
            "use lighter dependencies."
        )
    return True, f"package gate: ok ({len(names)} packages, ~{total_mb} MB)"


def wheelhouse_index_args() -> List[str]:
    """pip args pointing at the shared wheelhouse (Layer 1C) — faster
    installs and less egress. Accepts a local dir (--find-links, populated
    by scripts/build-wheelhouse.sh) or an index URL. No-op when unset."""
    url = os.getenv("WHEELHOUSE_URL", "").strip()
    if not url:
        return []
    if url.startswith("/"):
        return ["--find-links", url]
    return ["--extra-index-url", url]
