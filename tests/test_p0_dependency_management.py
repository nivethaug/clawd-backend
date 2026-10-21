"""P0 Dependency Management tests (plan: docs/DEPENDENCY_MANAGEMENT_PLAN.md).

Acceptance rows covered:
  1. Standard website dependencies remain unchanged (snapshot tripwire).
  2. Lockfile present, committed, valid, and survives the clone copy path.
  3+4. run_npm shared-cache behavior: concurrent installs keep separate
       node_modules/lockfiles, cache is shared, structured log emitted.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_FRONTEND = ROOT / "templates" / "blank-template" / "frontend"

# Snapshot of the standard template's dependencies (acceptance row 1).
# Any change here must be intentional — update this snapshot consciously.
STANDARD_DEPS = {
    "@hookform/resolvers": "^3.10.0",
    "@tanstack/react-query": "^5.83.0",
    "class-variance-authority": "^0.7.1",
    "clsx": "^2.1.1",
    "cmdk": "^1.1.1",
    "date-fns": "^3.6.0",
    "embla-carousel-react": "^8.6.0",
    "input-otp": "^1.4.2",
    "lucide-react": "^0.462.0",
    "next-themes": "^0.3.0",
    "react": "^18.3.1",
    "react-day-picker": "^8.10.1",
    "react-dom": "^18.3.1",
    "react-hook-form": "^7.61.1",
    "react-resizable-panels": "^2.1.9",
    "react-router-dom": "^6.30.1",
    "recharts": "^2.15.4",
    "sonner": "^1.7.4",
    "tailwind-merge": "^2.6.0",
    "tailwindcss-animate": "^1.0.7",
    "vaul": "^0.9.9",
    "zod": "^3.25.76",
}


class TestTemplateLockfile(unittest.TestCase):
    def test_lockfile_exists_and_valid(self):
        lock = TEMPLATE_FRONTEND / "package-lock.json"
        self.assertTrue(lock.is_file(), "template package-lock.json must be committed")
        data = json.loads(lock.read_text())
        self.assertEqual(data.get("lockfileVersion"), 3)
        self.assertGreater(len(data.get("packages", {})), 100)

    def test_lockfile_covers_every_runtime_dependency(self):
        pkg = json.loads((TEMPLATE_FRONTEND / "package.json").read_text())
        lock = json.loads((TEMPLATE_FRONTEND / "package-lock.json").read_text())
        lock_names = {p.rsplit("node_modules/", 1)[-1] for p in lock["packages"]}
        missing = [d for d in pkg.get("dependencies", {}) if d not in lock_names]
        self.assertEqual(missing, [], f"lockfile missing deps: {missing}")

    def test_gitignore_no_longer_ignores_lockfile(self):
        gi = (TEMPLATE_FRONTEND / ".gitignore").read_text()
        active = [l.strip() for l in gi.splitlines()
                  if l.strip() and not l.strip().startswith("#")]
        self.assertNotIn("package-lock.json", active,
                         ".gitignore must not ignore package-lock.json")

    def test_standard_dependencies_unchanged(self):
        pkg = json.loads((TEMPLATE_FRONTEND / "package.json").read_text())
        deps = pkg.get("dependencies", {})
        for name, version in STANDARD_DEPS.items():
            self.assertEqual(deps.get(name), version,
                             f"standard dep {name} changed: {deps.get(name)}")
        # No 3D deps leaked into the standard template (P2 guard).
        for banned in ("three", "@react-three/fiber", "@react-three/drei"):
            self.assertNotIn(banned, deps)


class TestLockfileSurvivalPaths(unittest.TestCase):
    def test_clone_skip_list_does_not_exclude_lockfile(self):
        """app.py _copy_project_files skips only DIRECTORIES; the lockfile is
        a file and must never appear in a skip list."""
        src = (ROOT / "app.py").read_text(encoding="utf-8", errors="replace")
        m = re.search(r'skip_dirs = (\{[^}]*\})', src)
        self.assertIsNotNone(m, "clone skip_dirs literal not found")
        skip = m.group(1)
        self.assertNotIn("package-lock.json", skip)
        self.assertIn("node_modules", skip)  # sanity: found the real literal

    def test_copy_with_clone_semantics_preserves_lockfile(self):
        """Replicates _copy_project_files semantics (dirs in skip list are
        skipped; files are copied)."""
        skip_dirs = {".git", "node_modules", "dist", ".next", "__pycache__",
                     "logs", ".cache", "build"}
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dst = Path(tmp) / "dst"
            (src / "frontend").mkdir(parents=True)
            (src / "frontend" / "package-lock.json").write_text('{"lockfileVersion": 3}')
            (src / "frontend" / "package.json").write_text("{}")
            (src / "frontend" / "node_modules" / "x").mkdir(parents=True)
            dst.mkdir()
            for item in os.listdir(src / "frontend"):
                s = src / "frontend" / item
                d = dst / item
                if os.path.isdir(s):
                    if item in skip_dirs:
                        continue
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
            self.assertTrue((dst / "package-lock.json").is_file())
            self.assertFalse((dst / "node_modules").exists())


@unittest.skipUnless(shutil.which("npm"), "npm not available")
class TestRunNpmSharedCache(unittest.TestCase):
    """Rows 3+4: concurrent installs, shared cache, isolation, logging."""

    def setUp(self):
        import services.npm_install as ni
        self.ni = ni
        self._orig_cache = ni.NPM_CACHE_DIR
        self.tmp = tempfile.mkdtemp(prefix="p0_npm_")
        self.cache = os.path.join(self.tmp, "shared-cache")
        ni.NPM_CACHE_DIR = self.cache
        self.projects = []
        for i, dep in enumerate((("ms", "^2.1.3"), ("uuid", "^9.0.1"))):
            p = os.path.join(self.tmp, f"proj{i}")
            os.makedirs(p)
            with open(os.path.join(p, "package.json"), "w") as f:
                json.dump({"name": f"p{i}", "version": "1.0.0",
                           "dependencies": {dep[0]: dep[1]}}, f)
            self.projects.append((p, dep[0]))
        # capture log records
        self.records = []
        self.handler = logging.Handler()
        self.handler.emit = lambda record: self.records.append(record)
        ni._log.addHandler(self.handler)
        ni._log.setLevel(logging.INFO)

    def tearDown(self):
        self.ni.NPM_CACHE_DIR = self._orig_cache
        self.ni._log.removeHandler(self.handler)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_concurrent_installs_shared_cache_isolation_and_logging(self):
        results = {}

        def run(project, name):
            results[name] = self.ni.run_npm(
                ["install", "--no-audit", "--progress=false"],
                cwd=project, timeout=180)

        threads = [threading.Thread(target=run, args=pp) for pp in self.projects]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for name, proc in results.items():
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr[:300]}")
        # isolation: each project has its OWN node_modules with its OWN dep
        for project, name in self.projects:
            nm = os.path.join(project, "node_modules", name)
            self.assertTrue(os.path.isdir(nm), f"{name} not in own node_modules")
        # cross-contamination: proj0 must NOT contain uuid, proj1 must NOT contain ms
        self.assertFalse(os.path.isdir(os.path.join(self.projects[0][0], "node_modules", "uuid")))
        self.assertFalse(os.path.isdir(os.path.join(self.projects[1][0], "node_modules", "ms")))
        # shared cache was used and structured log lines emitted
        self.assertTrue(os.path.isdir(self.cache), "shared cache dir not created")
        npm_lines = [r for r in self.records if "[NPM]" in r.getMessage()]
        self.assertEqual(len(npm_lines), 2)
        for r in npm_lines:
            msg = r.getMessage()
            self.assertIn("cache=", msg)
            self.assertIn("duration=", msg)
            self.assertIn("exit=0", msg)
            self.assertIn("node_modules_delta=", msg)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2).result.wasSuccessful() else 1)
