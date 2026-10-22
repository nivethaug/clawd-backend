"""P2 frontend-preset tests (plan: docs/DEPENDENCY_MANAGEMENT_PLAN.md).

Acceptance rows:
  1. Standard website deps remain unchanged (standard = strict no-op).
  6. A 3D project receives exactly its approved preset dependencies.
  8. Existing projects / template untouched by preset machinery.

The final test runs the REAL service (real registry + real lockfile-only
regen) against a copy of the actual template — it needs network + npm and
skips gracefully without them.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.deps import presets  # noqa: E402
from services.sandbox import npm_gate  # noqa: E402


class TestClassifyPreset(unittest.TestCase):
    def test_3d_briefs(self):
        for brief in (
            "Build a 3D product configurator for furniture",
            "A WebGL scene showing the solar system",
            "three.js portfolio with an interactive hero",
            "A first-person maze game in the browser",
        ):
            self.assertEqual(presets.classify_preset(brief), "3d", brief)

    def test_animated_briefs(self):
        for brief in (
            "Landing page with rich motion and animated transitions",
            "Portfolio focused on scroll animations and micro-interactions",
        ):
            self.assertEqual(presets.classify_preset(brief), "animated", brief)

    def test_standard_fallback(self):
        for brief in (
            "Simple bakery website with a menu and contact form",
            "SaaS dashboard with charts and user management",
            "", None,
            "A blog about game development",  # 'game' alone must NOT be 3d
        ):
            self.assertEqual(presets.classify_preset(brief), "standard", brief)

    def test_forced_override(self):
        with mock.patch.dict(os.environ, {"FORCE_FRONTEND_PRESET": "3d"}):
            self.assertEqual(presets.classify_preset("bakery site"), "3d")


class TestPresetSpecs(unittest.TestCase):
    def test_all_pins_are_exact_and_gate_parseable(self):
        for name, spec_list in (
            ("standard", presets.preset_specs("standard")),
            ("animated", presets.preset_specs("animated")),
            ("3d", presets.preset_specs("3d")),
        ):
            for spec in spec_list:
                n, v, err = npm_gate.parse_spec(spec)
                self.assertIsNone(err, f"{name}: {spec} -> {err}")

    def test_standard_is_empty(self):
        self.assertEqual(presets.preset_specs("standard"), [])

    def test_3d_has_exactly_three_deps(self):
        self.assertEqual(sorted(presets.preset_specs("3d")), [
            "@react-three/drei@9.122.0",
            "@react-three/fiber@8.18.0",
            "three@0.186.1",
        ])

    def test_no_physics_or_postprocessing_in_presets(self):
        blob = json.dumps(presets.PRESETS)
        self.assertNotIn("rapier", blob)
        self.assertNotIn("postprocessing", blob)


class TestApplyPresetStandardNoop(unittest.TestCase):
    def test_standard_never_touches_anything(self):
        result = presets.apply_preset("/nonexistent/path", "standard")
        self.assertTrue(result["ok"])
        self.assertEqual(result["applied"], [])

    def test_unknown_preset_falls_back_to_standard(self):
        result = presets.apply_preset("/nonexistent/path", "bogus")
        self.assertTrue(result["ok"])
        self.assertEqual(result["applied"], [])


@unittest.skipUnless(shutil.which("npm"), "npm not available")
class TestApply3dPresetReal(unittest.TestCase):
    """REAL service run on a copy of the actual template: registry fetch,
    package.json merge, lockfile-only regeneration. No node_modules needed."""

    def test_3d_preset_on_template_copy(self):
        # skip without network to the registry
        try:
            import httpx
            r = httpx.get("https://registry.npmjs.org/three", timeout=10)
            r.raise_for_status()
        except Exception:
            self.skipTest("registry unreachable")

        src = ROOT / "templates" / "blank-template" / "frontend"
        tmp = tempfile.mkdtemp(prefix="p2_3d_")
        try:
            frontend = Path(tmp) / "frontend"
            shutil.copytree(src, frontend,
                            ignore=shutil.ignore_patterns("node_modules"))
            # sanity: baseline deps
            pkg0 = json.loads((frontend / "package.json").read_text())
            self.assertNotIn("three", pkg0["dependencies"])

            # apply through the REAL service (registry + lockfile regen).
            # Gate runs in log-only default; pins are exact so structural
            # checks pass regardless.
            result = presets.apply_preset(tmp, "3d", install=False)
            self.assertTrue(result["ok"], result.get("message"))
            self.assertEqual(sorted(result["applied"]),
                             ["@react-three/drei@9.122.0",
                              "@react-three/fiber@8.18.0",
                              "three@0.186.1"])

            pkg = json.loads((frontend / "package.json").read_text())
            self.assertEqual(pkg["dependencies"]["three"], "0.186.1")
            self.assertEqual(pkg["dependencies"]["@react-three/fiber"], "8.18.0")
            self.assertEqual(pkg["dependencies"]["@react-three/drei"], "9.122.0")
            # existing deps untouched
            self.assertEqual(pkg["dependencies"]["react"], "^18.3.1")

            # lockfile regenerated and resolves the new pins
            lock = json.loads((frontend / "package-lock.json").read_text())
            self.assertIn("node_modules/three", lock["packages"])
            self.assertIn("node_modules/@react-three/fiber", lock["packages"])
            self.assertIn("node_modules/@react-three/drei", lock["packages"])

            # and a cold `npm ci --dry-run` (acceptance: cold install works)
            import subprocess
            npm_bin = shutil.which("npm") or "npm"
            proc = subprocess.run(
                [npm_bin, "ci", "--dry-run", "--no-audit", "--progress=false"],
                cwd=str(frontend), capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2).result.wasSuccessful() else 1)
