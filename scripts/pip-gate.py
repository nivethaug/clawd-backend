#!/usr/bin/env python3
"""
pip-gate — a transparent pip shim for project sandboxes.

Installed as `pip`/`pip3` earlier in PATH by the sandbox wrapper scripts.
Every `pip install` is checked against services/sandbox/package_gate.py
(blocked LLM/GPU runtimes + total size cap) BEFORE the real pip runs.
Non-install subcommands pass through untouched. Failures in the gate
itself fail CLOSED for `install` (the point of the gate) but never affect
other subcommands.
"""
import os
import subprocess
import sys


def _real_pip() -> str:
    """Path to the real pip: this shim lives next to it (pip-gate.py in the
    same bin dir as pip), or fall back to python -m pip."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "pip.real"), os.path.join(here, "pip3.real")):
        if os.path.isfile(cand):
            return cand
    return None


def _requirements_from_args(argv: list) -> list:
    """Extract requirement strings from a pip install command line."""
    reqs = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-r", "--requirement", "-c", "--constraint"):
            i += 1
            if i < len(argv):
                try:
                    with open(argv[i], encoding="utf-8") as fh:
                        reqs.extend(l.strip() for l in fh if l.strip())
                except Exception:
                    pass
        elif a in ("-e", "--editable", "--index-url", "--extra-index-url",
                   "--find-links", "-f", "--prefix", "--src", "-t", "--target"):
            i += 1  # skip its value
        elif a.startswith("-"):
            pass
        else:
            reqs.append(a)
        i += 1
    return [r for r in reqs if r]


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] not in ("install", "download", "wheel"):
        real = _real_pip()
        if real:
            os.execv(real, [real] + argv)
        return subprocess.call([sys.executable, "-m", "pip"] + argv)

    reqs = _requirements_from_args(argv)
    try:
        # package_gate.py sits next to this shim (copied there by the
        # sandbox wrapper) — stdlib-only fallback if httpx is absent.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from package_gate import gate_requirements, wheelhouse_index_args
        ok, message = gate_requirements(reqs)
    except Exception as e:  # fail closed
        print(f"pip-gate: gate check failed ({e}); refusing install "
              "as a precaution. Report this to the platform.", file=sys.stderr)
        return 2
    if not ok:
        print(f"pip-gate: BLOCKED — {message}", file=sys.stderr)
        return 2

    cmd = [_real_pip()] if _real_pip() else [sys.executable, "-m", "pip"]
    cmd += argv + wheelhouse_index_args()
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
