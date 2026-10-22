"""P3 fast tests: lazy-3D preset support files (build benchmarks live in
scripts/bundle_benchmark.py — run separately; they need npm + network)."""
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


class TestPresetSupportFiles(unittest.TestCase):
    def _make_project(self):
        tmp = tempfile.mkdtemp(prefix="p3_")
        frontend = Path(tmp) / "frontend"
        (frontend / "src").mkdir(parents=True)
        (frontend / "package.json").write_text('{"name":"t","dependencies":{}}')
        return tmp, frontend

    def test_3d_preset_installs_lazy_wrapper(self):
        tmp, frontend = self._make_project()
        try:
            # dep application + install mocked; file copy is what we assert
            from services.deps import frontend_deps
            fake = mock.Mock(return_value={"ok": True, "added": ["three@0.186.1"]})
            import services.npm_install as ni
            with mock.patch.object(frontend_deps, "add_frontend_deps", fake):
                with mock.patch.object(ni, "run_npm", mock.Mock(returncode=0)):
                    result = presets.apply_preset(tmp, "3d", install=True)
            self.assertTrue(result["ok"], result)
            wrapper = frontend / "src" / "lib" / "lazy3d.tsx"
            self.assertTrue(wrapper.is_file(),
                            "src/lib/lazy3d.tsx must be installed by the 3d preset")
            body = wrapper.read_text(encoding="utf-8")
            # lazy + Suspense + dynamic imports only — no eager three import
            self.assertIn("lazy(", body)
            self.assertIn("import('@react-three/fiber')", body)
            self.assertNotIn('from "three"', body.split("loadThree")[0],
                             "no eager three import before the loader definition")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_standard_preset_installs_no_files(self):
        tmp, frontend = self._make_project()
        try:
            presets.apply_preset(tmp, "standard")
            self.assertFalse((frontend / "src" / "lib" / "lazy3d.tsx").exists())
            self.assertEqual(list((frontend / "src").iterdir()), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_wrapper_uses_dynamic_imports_only(self):
        """The shipped wrapper must never eagerly import fiber/drei/three —
        that would defeat the chunk split (see docs/BENCHMARKS.md)."""
        wrapper = (ROOT / "services" / "deps" / "preset_files" / "3d" /
                   "lib" / "lazy3d.tsx").read_text(encoding="utf-8")
        for top in wrapper.splitlines():
            s = top.strip()
            if s.startswith("import ") and " from " in s:
                # only react may be imported statically
                self.assertIn("from 'react'", s, f"static import not allowed: {s}")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2).result.wasSuccessful() else 1)


class TestManualChunksPatch(unittest.TestCase):
    CFG = ("export default defineConfig(({ mode }) => ({" + chr(10)
           + "  server: { port: 8080 }," + chr(10)
           + "  plugins: [react()]," + chr(10)
           + "}));" + chr(10))

    def _project_with_config(self):
        import tempfile
        tmp = tempfile.mkdtemp(prefix="p3mc_")
        frontend = Path(tmp) / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "vite.config.ts").write_text(self.CFG)
        return tmp, frontend

    def _rmtree(self, tmp):
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_patch_adds_rule_and_is_idempotent(self):
        tmp, frontend = self._project_with_config()
        try:
            presets._patch_vite_manual_chunks(tmp)
            cfg1 = (frontend / "vite.config.ts").read_text()
            self.assertIn("manualChunks", cfg1)
            self.assertIn("three-vendor", cfg1)
            presets._patch_vite_manual_chunks(tmp)
            self.assertEqual(cfg1, (frontend / "vite.config.ts").read_text(), "idempotent")
        finally:
            self._rmtree(tmp)

    def test_apply_preset_3d_invokes_patch(self):
        tmp, frontend = self._project_with_config()
        try:
            from services.deps import frontend_deps
            fake = mock.Mock(return_value={"ok": True, "added": ["three@0.186.1"]})
            import services.npm_install as ni
            with mock.patch.object(frontend_deps, "add_frontend_deps", fake):
                with mock.patch.object(ni, "run_npm", mock.Mock(returncode=0)):
                    presets.apply_preset(tmp, "3d", install=False)
            self.assertIn("manualChunks", (frontend / "vite.config.ts").read_text())
        finally:
            self._rmtree(tmp)

    def test_standard_preset_never_touches_vite_config(self):
        tmp, frontend = self._project_with_config()
        try:
            presets.apply_preset(tmp, "standard")
            self.assertEqual((frontend / "vite.config.ts").read_text(), self.CFG)
        finally:
            self._rmtree(tmp)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2).result.wasSuccessful() else 1)
