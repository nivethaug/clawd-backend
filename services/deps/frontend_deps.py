"""
Sanctioned frontend-dependency service (Dependency Management Plan, P1).

THE only code path that may add npm dependencies to a project's frontend.
Flows (creation presets in P2, chat-driven additions) must call this —
direct package.json editing stays forbidden everywhere else.

Flow per call:
  1. npm gate (services/sandbox/npm_gate.py): blocklist, exact pins,
     registry verification, lifecycle scripts, peer conflicts, size cap
     (fail-closed under NPM_GATE_ENFORCE=1; log-only while rolling out).
  2. file_utils.check_package_json (typosquat guard) on the merged file.
  3. Atomic write through FileUtils.write_file (all existing layers:
     denylist paths, malware signatures, install-script blocking).
  4. Lockfile regeneration WITHOUT installing node_modules:
     `npm install --package-lock-only` via services.npm_install.run_npm
     (shared cache + structured logging, P0). A failure here rolls the
     package.json write back.
  5. Git commit of package.json + package-lock.json (project repo; the
     file-ops guard pattern). No rebuild here — callers decide.

Does NOT run a full install or build; the next buildpublish picks the new
deps + lockfile up through the normal npm ci path.
"""
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from file_utils import FileUtils
from services.npm_install import run_npm
from services.sandbox import npm_gate

logger = logging.getLogger("services.deps.frontend_deps")


def add_frontend_deps(
    project_path: str,
    packages: List[str],
    enforce: Optional[bool] = None,
) -> Dict:
    """Add pinned npm dependencies to <project>/frontend.

    Returns {"ok": bool, "gate": {...}, "added": [...], "message": str}.
    `enforce` overrides NPM_GATE_ENFORCE for this call (None = env).
    """
    frontend = Path(project_path) / "frontend"
    pkg_path = frontend / "package.json"

    if not pkg_path.is_file():
        return {"ok": False, "message": "frontend/package.json not found",
                "gate": {"decisions": []}, "added": []}
    if not packages:
        return {"ok": False, "message": "no packages requested",
                "gate": {"decisions": []}, "added": []}

    if enforce is not None:
        os.environ["NPM_GATE_ENFORCE"] = "1" if enforce else "0"
    try:
        current = json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "message": f"package.json unreadable: {e}",
                "gate": {"decisions": []}, "added": []}

    deps: Dict[str, str] = dict(current.get("dependencies") or {})

    # 1. gate against the project's CURRENT dependency set (peer checks)
    allowed, decisions, message = npm_gate.gate_packages(packages, current_deps=deps)
    gate_result = {"allowed": allowed, "decisions": decisions,
                   "message": message, "mode": "enforce" if npm_gate.enforce_enabled() else "log-only"}
    if not allowed:
        logger.warning("[DEPS] gate rejected %s for %s: %s",
                       packages, project_path, message)
        return {"ok": False, "gate": gate_result, "added": [], "message": message}

    # 2+3. merge + write through FileUtils (typosquat guard runs inside
    # check_package_json via write_file's Layer 3)
    old_content = pkg_path.read_text(encoding="utf-8")
    for d in decisions:
        name, version, err = npm_gate.parse_spec(d["spec"])
        deps[name] = version
    current["dependencies"] = dict(sorted(deps.items()))
    new_content = json.dumps(current, indent=2, ensure_ascii=False) + "\n"

    issues = FileUtils.check_package_json(old_content, new_content)
    if issues:
        return {"ok": False, "gate": gate_result, "added": [],
                "message": "package.json guard: " + "; ".join(issues)}

    try:
        FileUtils.write_file(str(frontend), "package.json", new_content)
    except Exception as e:
        return {"ok": False, "gate": gate_result, "added": [],
                "message": f"write failed: {e}"}

    # 4. regenerate lockfile only (no node_modules). On failure, roll back.
    lock_result = run_npm(
        ["install", "--package-lock-only", "--no-audit", "--progress=false"],
        cwd=str(frontend), timeout=300, logger=logger)
    if lock_result.returncode != 0:
        logger.error("[DEPS] lockfile regeneration failed for %s — rolling back",
                     project_path)
        try:
            FileUtils.write_file(str(frontend), "package.json", old_content)
        except Exception:
            logger.exception("[DEPS] rollback write failed for %s", project_path)
        return {"ok": False, "gate": gate_result, "added": [],
                "message": "lockfile regeneration failed (rolled back): "
                           + (lock_result.stderr or "")[:300]}

    added = [d["spec"] for d in decisions]

    # 5. commit both files (project-local git; no push here)
    try:
        subprocess.run(["git", "add", "package.json", "package-lock.json"],
                       cwd=str(frontend), capture_output=True, timeout=30)
        subprocess.run(
            ["git", "commit", "-m", f"deps: add {', '.join(added)}",
             "--no-verify"],
            cwd=str(frontend), capture_output=True, timeout=30)
    except Exception as e:  # non-fatal: files are already in place
        logger.warning("[DEPS] git commit skipped (%s): %s", project_path, e)

    logger.info("[DEPS] added %s to %s (mode=%s)", added, project_path,
                gate_result["mode"])
    return {"ok": True, "gate": gate_result, "added": added,
            "message": f"added {', '.join(added)} — rebuild to activate"}
