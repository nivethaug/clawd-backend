#!/usr/bin/env python3
"""
npm Gate (Dependency Management Plan, P1) — the security gate for adding
frontend npm dependencies to projects. Mirrors services/sandbox/package_gate.py
(the pip gate) but is STRICTER in two ways by design:

  * Versions must be EXACT pins (name@1.2.3). No ranges, no "latest".
  * FAIL CLOSED: if registry metadata cannot be fetched or verified, the
    package is rejected (the pip gate fails open; for npm the plan
    explicitly requires fail-closed).

What it checks per requested package (name@exact-version):
  1. Blocklist (built-in + NPM_BLOCKED_PACKAGES, wildcards as "prefix-*").
  2. Exact pinned version.
  3. Registry metadata (registry.npmjs.org): package exists, version exists.
  4. Lifecycle scripts: any preinstall/install/postinstall/prepare in the
     version's metadata is rejected (same policy as file_utils blocks
     install scripts in package.json).
  5. Peer dependencies vs the project's CURRENT dependencies (e.g. a package
     requiring react ^19 must not land in a react 18.3.1 project). Conflicts
     are rejected; unparsable peers are reported, not fatal.
  6. Per-operation total size cap via dist.unpackedSize (NPM_MAX_INSTALL_MB,
     default 300) — missing size metadata = unverifiable = rejected.
  7. Transitive report (dependency count) — informational, logged.

Enforcement: NPM_GATE_ENFORCE (default "0" = LOG-ONLY per the plan's rollout:
the gate records every decision but does not block until adversarial tests
pass in staging). Set to "1" to enforce.

Env knobs:
  NPM_BLOCKED_PACKAGES   comma list appended to the built-in blocklist
  NPM_MAX_INSTALL_MB     max total unpacked size per add-deps op (default 300)
  NPM_GATE_ENFORCE       "1" = block on failure, "0"/unset = log-only
"""

import fnmatch
import json
import logging
import os
import re
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("services.sandbox.npm_gate")

# npm equivalents of the pip disk-killers + known-dangerous package shapes.
# Wildcards allowed as "prefix-*".
DEFAULT_BLOCKED = {
    # GPU/ML runtimes that belong behind APIs, not in static website builds
    "torch", "tensorflow", "@tensorflow/tfjs", "@tensorflow/tfjs-node",
    "transformers-js", "onnxruntime-node",
    # native/build toolchains a website project has no business pulling
    "node-gyp", "prebuild-install", "cmake-js", "node-canvas", "canvas",
    "sharp-cli", "electron", "electron-builder", "pkg", "nexe",
    # crypto miners / known-abused names
    "cryptonight-hashing", "*miner*",
}

_DEFAULT_MAX_MB = 300
_REGISTRY = "https://registry.npmjs.org"
_REGISTRY_TIMEOUT = 10.0

# exact pin: 1.2.3 or 1.2.3-rc.1 (no ranges, no tags)
_PIN_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?$")
_NAME_RE = re.compile(r"^(@[a-z0-9][a-z0-9-]*/)?[a-z0-9][a-z0-9._-]*$", re.I)


def blocked_packages() -> set:
    extra = os.getenv("NPM_BLOCKED_PACKAGES", "")
    merged = set(DEFAULT_BLOCKED)
    for name in extra.split(","):
        name = name.strip().lower()
        if name:
            merged.add(name)
    return merged


def max_install_mb() -> int:
    try:
        return max(20, int(os.getenv("NPM_MAX_INSTALL_MB", _DEFAULT_MAX_MB)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_MB


def enforce_enabled() -> bool:
    return os.getenv("NPM_GATE_ENFORCE", "0").strip().lower() in ("1", "true", "yes")


def is_blocked(name: str, blocklist: Optional[set] = None) -> Optional[str]:
    blocklist = blocklist if blocklist is not None else blocked_packages()
    n = name.strip().lower()
    for entry in blocklist:
        if "*" in entry:
            if fnmatch.fnmatch(n, entry):
                return entry
        elif n == entry:
            return entry
    return None


# ---------------------------------------------------------------- registry --
# Injectable for tests: fetch(name) -> dict | None (None = unreachable).
_fetcher: Optional[Callable[[str], Optional[dict]]] = None


def set_registry_fetcher(fetch: Optional[Callable[[str], Optional[dict]]]) -> None:
    """Test hook: replace the network fetch (registry JSON or None)."""
    global _fetcher
    _fetcher = fetch


def _registry_fetch(name: str) -> Optional[dict]:
    if _fetcher is not None:
        return _fetcher(name)
    try:
        import httpx
        r = httpx.get(
            f"{_REGISTRY}/{name}",
            timeout=_REGISTRY_TIMEOUT,
            headers={"User-Agent": "dreamagent-npm-gate/1.0"},
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:  # noqa: BLE001 — gate must never crash callers
        logger.warning("npm_gate registry lookup failed for %s: %s", name, e)
        return None


# ------------------------------------------------------------------ semver --
def _version_tuple(v: str) -> Optional[Tuple[int, int, int]]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", v or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _range_conflicts(peer_range: str, have_version: str) -> Optional[str]:
    """Return a human reason if `have_version` clearly cannot satisfy
    `peer_range`, else None. Simple ^/~/>=/exact handling; anything
    unparsable returns None (reported, not fatal)."""
    have = _version_tuple(have_version)
    if have is None:
        return None
    rng = (peer_range or "").strip()
    if not rng or rng == "*":
        return None
    # take the first alternative of an "||" chain
    rng = rng.split("||")[0].strip()
    m = re.match(r"^(\^|~|>=|<=|>|<)?\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", rng)
    if not m:
        return None
    op = m.group(1) or ""
    major, minor = int(m.group(2)), int(m.group(3) or 0)
    patch = int(m.group(4) or 0)
    want = (major, minor, patch)
    if op == "^":
        ok = have[0] == want[0] and have >= want
    elif op == "~":
        ok = have[:2] == want[:2] and have >= want
    elif op in (">=", ">"):
        ok = have > want if op == ">" else have >= want
    elif op in ("<=", "<"):
        ok = have < want if op == "<" else have <= want
    else:  # exact-ish
        ok = have[0] == want[0] and (want[1] == 0 or have[1] == want[1]) \
            and (want[2] == 0 or have[2] == want[2])
    return None if ok else f"peer needs {peer_range!r}, project has {have_version}"


# -------------------------------------------------------------------- gate --
def parse_spec(spec: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """'name@1.2.3' -> (name, version, error)."""
    spec = (spec or "").strip()
    if not spec:
        return None, None, "empty spec"
    if spec.startswith("@"):
        name, sep, version = spec[1:].partition("@")
        name = "@" + name
    else:
        name, sep, version = spec.partition("@")
    if not sep or not version:
        return name, None, "missing exact pinned version (use name@x.y.z)"
    if not _NAME_RE.match(name):
        return name, version, f"invalid package name {name!r}"
    if not _PIN_RE.match(version):
        return name, version, (
            f"version {version!r} is not an exact pin "
            "(ranges/tags/latest are not allowed; use name@x.y.z)")
    return name, version, None


def gate_packages(
    specs: List[str],
    current_deps: Optional[Dict[str, str]] = None,
) -> Tuple[bool, List[dict], str]:
    """Evaluate every requested spec. Returns (allowed, decisions, message).

    `allowed` respects NPM_GATE_ENFORCE: in log-only mode structural
    rejections (bad pin, blocklist) still block — those need no network —
    but metadata-verifiability failures are logged and the op proceeds.
    In enforce mode every failure blocks.
    """
    current_deps = current_deps or {}
    blocklist = blocked_packages()
    cap = max_install_mb()
    enforce = enforce_enabled()
    decisions: List[dict] = []
    failures: List[str] = []
    total_mb = 0.0

    for spec in specs:
        name, version, err = parse_spec(spec)
        if err:
            decisions.append({"spec": spec, "ok": False, "reason": err})
            failures.append(f"{spec}: {err}")
            continue

        hit = is_blocked(name, blocklist)
        if hit:
            reason = (f"'{name}' is on the npm blocklist (matched '{hit}'). "
                      "This class of package is not installable in projects.")
            decisions.append({"spec": spec, "ok": False, "reason": reason})
            failures.append(f"{name}: {reason}")
            continue

        meta = _registry_fetch(name)
        if meta is None:
            reason = (f"registry metadata for '{name}' could not be verified "
                      "(unreachable/not found). Fail-closed: package rejected.")
            decisions.append({"spec": spec, "ok": False, "reason": reason,
                              "fail_closed": True})
            if enforce:
                failures.append(f"{name}: {reason}")
            else:
                logger.warning("[NPM-GATE] log-only, would fail closed: %s %s",
                               name, reason)
            continue

        versions = meta.get("versions") or {}
        vmeta = versions.get(version)
        if vmeta is None:
            reason = f"version {version} of '{name}' does not exist on the registry"
            decisions.append({"spec": spec, "ok": False, "reason": reason})
            failures.append(f"{name}@{version}: {reason}")
            continue

        # lifecycle scripts of the package itself
        scripts = ((vmeta.get("scripts") or {}))
        bad_scripts = [s for s in ("preinstall", "install", "postinstall", "prepare")
                       if scripts.get(s)]
        if bad_scripts:
            reason = (f"'{name}' declares lifecycle script(s) {bad_scripts} — "
                      "install scripts are blocked by platform policy")
            decisions.append({"spec": spec, "ok": False, "reason": reason})
            failures.append(f"{name}: {reason}")
            continue

        # size (unpacked) — missing = unverifiable = fail closed in enforce
        size_b = ((vmeta.get("dist") or {}).get("unpackedSize"))
        if size_b is None:
            reason = ("unpackaged size not published for this version — "
                      "unverifiable, fail-closed")
            decisions.append({"spec": spec, "ok": False, "reason": reason,
                              "fail_closed": True})
            if enforce:
                failures.append(f"{name}: {reason}")
            else:
                logger.warning("[NPM-GATE] log-only, would fail closed: %s %s",
                               name, reason)
            continue
        size_mb = size_b / (1024 * 1024)
        total_mb += size_mb

        # peer dependencies vs what the project already has
        peers = vmeta.get("peerDependencies") or {}
        peer_problems = []
        for pname, prange in peers.items():
            have = current_deps.get(pname)
            if have:
                conflict = _range_conflicts(prange, have)
                if conflict:
                    peer_problems.append(f"{pname}: {conflict}")
        if peer_problems:
            reason = "peer dependency conflict — " + "; ".join(peer_problems)
            decisions.append({"spec": spec, "ok": False, "reason": reason})
            failures.append(f"{name}: {reason}")
            continue

        transitive = len(vmeta.get("dependencies") or {})
        decisions.append({
            "spec": spec, "ok": True, "size_mb": round(size_mb, 2),
            "transitive_deps": transitive,
            "peers": peers,
        })

    if total_mb > cap:
        msg = f"total unpacked size {total_mb:.1f}MB exceeds cap {cap}MB"
        for d in decisions:
            if d.get("ok"):
                d["ok"] = False
                d["reason"] = msg
        failures.append(msg)

    message = "ok" if not failures else "; ".join(failures)
    allowed = not failures
    if enforce:
        logger.info("[NPM-GATE] enforce=%s allowed=%s specs=%d cap=%.0fMB",
                    enforce, allowed, len(specs), cap)
    return allowed, decisions, message
