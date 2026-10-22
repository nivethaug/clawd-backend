"""
Intelligent frontend presets (Dependency Management Plan, P2).

Presets add EXACT-PINNED npm dependencies to a freshly copied blank
template, classified from the creation brief. The standard preset is a
strict NO-OP — the template stays byte-identical (acceptance row 1).

Design rules (plan P2):
  * Selection is deterministic keyword classification with fallback =
    standard (a classifier miss can never leave a project without deps).
  * Versions are registry-verified at implementation time (see PRESETS)
    and must stay exact pins so the P1 npm gate accepts them.
  * Application routes EXCLUSIVELY through the P1 sanctioned service
    (services/deps/frontend_deps.add_frontend_deps) — package.json is
    never edited directly here.
  * Physics/postprocessing extras are NOT part of the 3D preset; they are
    added on demand post-creation via POST /projects/{id}/frontend/deps.

Pins verified against registry.npmjs.org on 2026-10-22:
  three@0.186.1                 (no peers, ~20MB unpacked)
  @react-three/fiber@8.18.0     (peers react >=18 <19 — React 18.3.1 OK;
                                 fiber v9 requires React 19 → excluded)
  @react-three/drei@9.122.0     (peers react ^18, @react-three/fiber ^8)
  framer-motion@11.18.2         (peers react ^18 || ^19)
"""
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger("services.deps.presets")

PRESETS: Dict[str, Dict] = {
    # standard = today's blank template, byte-identical. NEVER add deps here.
    "standard": {"deps": {}},
    "animated": {
        "deps": {"framer-motion": "11.18.2"},
    },
    "3d": {
        "deps": {
            "three": "0.186.1",
            "@react-three/fiber": "8.18.0",
            "@react-three/drei": "9.122.0",
        },
    },
}

# Deterministic keyword rules, checked in order (first match wins).
# Conservative: a brief must clearly ask for 3D; everything else is standard.
_RULES: List[tuple] = [
    ("3d", (
        "3d", "three.js", "threejs", "three js", "webgl", "webgpu",
        "first-person", "first person", "virtual world", "3-d scene",
        "3d scene", "3d game", "3d world", "3d visualization",
        "3d product", "3d configurator", "orbit a 3d", "rotate a 3d",
    )),
    ("animated", (
        "heavy animation", "rich motion", "motion design",
        "scroll animations", "micro-interactions", "microinteractions",
        "animated transitions", "physics-based ui",
    )),
]

# Optional escape hatch for testing/ops: FORCE_FRONTEND_PRESET=standard|animated|3d


def classify_preset(description: Optional[str]) -> str:
    """Deterministic brief → preset. Fallback is ALWAYS 'standard'."""
    forced = os.getenv("FORCE_FRONTEND_PRESET", "").strip().lower()
    if forced in PRESETS:
        return forced
    text = (description or "").lower()
    for preset, keywords in _RULES:
        for kw in keywords:
            if kw in text:
                logger.info("[PRESET] brief matched '%s' via keyword %r", preset, kw)
                return preset
    return "standard"


def preset_specs(preset: str) -> List[str]:
    """The preset's dependency specs as name@exact-version list."""
    return [f"{name}@{version}"
            for name, version in PRESETS.get(preset, {}).get("deps", {}).items()]


def _copy_preset_files(project_path: str, preset: str) -> None:
    """Copy services/deps/preset_files/<preset>/** into the project frontend
    (src/ tree). No-op when the preset has no files (standard)."""
    import shutil
    src_dir = os.path.join(os.path.dirname(__file__), "preset_files", preset)
    frontend_src = os.path.join(project_path, "frontend", "src")
    if not os.path.isdir(src_dir) or not os.path.isdir(frontend_src):
        return
    for root, _dirs, files in os.walk(src_dir):
        for f in files:
            s = os.path.join(root, f)
            rel = os.path.relpath(s, src_dir)
            d = os.path.join(frontend_src, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            logger.info("[PRESET] installed support file src/%s (%s)", rel, preset)


def apply_preset(project_path: str, preset: str,
                 install: bool = True) -> Dict:
    """Apply a preset to <project>/frontend via the P1 sanctioned service.

    With install=True and node_modules already present (fresh template
    copy), an incremental `npm install` reuses it and only fetches the new
    packages — preserving the create-time skip-install optimization.
    Standard preset = strict no-op (returns without touching anything).
    """
    if preset not in PRESETS:
        logger.warning("[PRESET] unknown preset %r — falling back to standard", preset)
        preset = "standard"
    specs = preset_specs(preset)
    if not specs:
        logger.info("[PRESET] standard preset — template unchanged")
        return {"ok": True, "preset": "standard", "applied": [], "message": "standard"}

    from services.deps.frontend_deps import add_frontend_deps
    from services.npm_install import run_npm
    import subprocess

    result = add_frontend_deps(project_path, specs)
    if not result.get("ok"):
        logger.error("[PRESET] %s preset failed for %s: %s",
                     preset, project_path, result.get("message"))
        return {"ok": False, "preset": preset, "applied": [],
                "message": result.get("message", "preset application failed")}

    # Preset support files (P3): e.g. the lazy 3D wrapper so Vite
    # code-splits three/fiber/drei out of the initial bundle.
    _copy_preset_files(project_path, preset)

    # Incremental install: the fresh template copy has node_modules; npm
    # install adds only the new packages (Phase 5 then skips its own ci).
    installed = False
    if install:
        frontend = os.path.join(project_path, "frontend")
        has_nm = os.path.isdir(os.path.join(frontend, "node_modules"))
        proc = run_npm(["install", "--no-audit", "--progress=false"],
                       cwd=frontend, timeout=600, logger=logger)
        installed = proc.returncode == 0
        if not installed:
            logger.warning(
                "[PRESET] incremental npm install failed for %s — Phase 5 "
                "will run a full npm ci (node_modules present: %s)",
                project_path, has_nm)

    logger.info("[PRESET] applied %s to %s (installed=%s)", preset, project_path, installed)
    return {"ok": True, "preset": preset, "applied": result["added"],
            "installed": installed,
            "message": f"preset {preset} applied: {', '.join(result['added'])}"}


# Extra capability packages addable post-creation via the P1 endpoint —
# surfaced to agent prompts so the sanctioned route is known.
ON_DEMAND_EXTRAS = {
    "physics": "@react-three/rapier",
    "postprocessing": "@react-three/postprocessing",
}
