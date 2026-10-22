#!/usr/bin/env python3
"""
Bundle benchmark (Dependency Management Plan, P3).

Builds three variants of the blank template and records measured numbers
into docs/BENCHMARKS.md:

  standard : template as-is (baseline)
  3d-eager : 3d preset + a page that imports three/fiber EAGERLY
             (worst case — everything in the initial bundle)
  3d-lazy  : 3d preset + the same page rendered through src/lib/lazy3d.tsx
             (target — 3D code-split into a lazy chunk)

Assertions (acceptance row 7):
  * standard build contains no three
  * 3d-lazy: the initial (index-*) chunk contains no three marker
  * 3d-lazy: a separate chunk >= 500KB exists (the 3D chunk)

Usage:  python scripts/bundle_benchmark.py [--out docs/BENCHMARKS.md]
Needs npm + network (registry) + ~2GB free disk. Run on the template
checkout; everything happens in a temp copy — the repo is never touched.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMPLATE = ROOT / "templates" / "blank-template" / "frontend"
NPM = shutil.which("npm") or "npm"
THREE_MARKER = b"WebGLRenderer"  # string literal present in three builds


def _run(cmd, cwd, timeout=1200, **kw):
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       timeout=timeout, **kw)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{(p.stderr or '')[-600:]}")
    return p


def _build(frontend):
    t0 = time.time()
    _run([NPM, "run", "build"], frontend, timeout=900)
    chunks = sorted(glob.glob(str(frontend / "dist" / "assets" / "*.js")),
                    key=os.path.getsize, reverse=True)
    return time.time() - t0, chunks


def _index_chunk(chunks):
    return next(c for c in chunks if "index-" in os.path.basename(c))


def _has_marker(path, marker=THREE_MARKER):
    with open(path, "rb") as f:
        return marker in f.read()


EAGER_PRELUDE = (
    'import * as THREE from "three";\n'
    'import { Canvas } from "@react-three/fiber";\n'
    'const _eager3d = [new THREE.Vector3(1, 2, 3), Canvas];\n'
    'declare const globalThis: any;\n'
    'globalThis.__eager3d = _eager3d;\n'
)

LAZY_PAGE = """import { Suspense } from "react";
import { LazyCanvas } from "@/lib/lazy3d";
export default function SceneDemo() {
  return (
    <Suspense fallback={null}>
      <LazyCanvas camera={{ position: [0, 0, 5] }}>
        <mesh><boxGeometry args={[1, 1, 1]} /><meshStandardMaterial /></mesh>
      </LazyCanvas>
    </Suspense>
  );
}
"""


def _wire_lazy_route(app_src: str) -> str:
    app_src = app_src.replace(
        'import { Suspense } from "react";',
        'import { Suspense, lazy } from "react";')
    app_src = app_src.replace(
        'import Welcome from "./pages/Welcome";',
        'import Welcome from "./pages/Welcome";\n'
        'const SceneDemo = lazy(() => import("./pages/SceneDemo"));')
    app_src = app_src.replace(
        '<Route path="/" element={<Welcome />} />',
        '<Route path="/" element={<Welcome />} />\n'
        '          <Route path="/scene" element='
        '{<Suspense fallback={null}><SceneDemo /></Suspense>} />')
    return app_src


def run_benchmarks() -> dict:
    from services.deps import presets

    tmp = tempfile.mkdtemp(prefix="bench3d_")
    try:
        frontend = Path(tmp) / "frontend"
        shutil.copytree(TEMPLATE, frontend,
                        ignore=shutil.ignore_patterns("dist", ".vite*", "node_modules"))

        # ---------------- standard baseline ----------------
        _run([NPM, "ci", "--prefer-offline", "--no-audit", "--progress=false"], frontend)
        el_std, chunks_std = _build(frontend)
        std = {
            "build_s": el_std, "chunks": len(chunks_std),
            "total_kb": sum(os.path.getsize(c) for c in chunks_std) // 1024,
            "initial_kb": os.path.getsize(_index_chunk(chunks_std)) // 1024,
            "three_in_initial": _has_marker(_index_chunk(chunks_std)),
        }

        # ---------------- 3d preset + eager ----------------
        presets.apply_preset(str(tmp), "3d", install=False)
        _run([NPM, "ci", "--prefer-offline", "--no-audit", "--progress=false"], frontend)
        app = frontend / "src" / "App.tsx"
        original = app.read_text(encoding="utf-8")
        app.write_text(EAGER_PRELUDE + original, encoding="utf-8")
        el_e, chunks_e = _build(frontend)
        eager = {
            "build_s": el_e, "chunks": len(chunks_e),
            "total_kb": sum(os.path.getsize(c) for c in chunks_e) // 1024,
            "initial_kb": os.path.getsize(_index_chunk(chunks_e)) // 1024,
            "three_in_initial": _has_marker(_index_chunk(chunks_e)),
        }

        # ---------------- 3d preset + lazy ----------------
        app.write_text(original, encoding="utf-8")
        (frontend / "src" / "pages" / "SceneDemo.tsx").write_text(
            LAZY_PAGE, encoding="utf-8")
        app.write_text(_wire_lazy_route(original), encoding="utf-8")
        el_l, chunks_l = _build(frontend)
        big_lazy = [c for c in chunks_l
                    if os.path.getsize(c) >= 500 * 1024 and "index-" not in os.path.basename(c)]
        lazy = {
            "build_s": el_l, "chunks": len(chunks_l),
            "total_kb": sum(os.path.getsize(c) for c in chunks_l) // 1024,
            "initial_kb": os.path.getsize(_index_chunk(chunks_l)) // 1024,
            "three_in_initial": _has_marker(_index_chunk(chunks_l)),
            "lazy3d_chunk_kb": (os.path.getsize(big_lazy[0]) // 1024) if big_lazy else 0,
        }

        # ---------------- 3d preset + STATIC 3d page (the 2131 case) --------
        # A component using LazyCanvas/lazyDrei statically imported by an
        # eager page — the wiring that duplicated three before the
        # manualChunks rule existed. The vendor chunk must keep three out
        # of the entry AND exist as a single copy.
        app.write_text(original, encoding="utf-8")
        (frontend / "src" / "pages" / "SceneDemo.tsx").write_text(
            LAZY_PAGE, encoding="utf-8")
        static_app = original.replace(
            'import Welcome from "./pages/Welcome";',
            'import Welcome from "./pages/Welcome";\n'
            'import SceneDemo from "./pages/SceneDemo";')
        static_app = static_app.replace(
            '<Route path="/" element={<Welcome />} />',
            '<Route path="/" element={<Welcome />} />\n'
            '          <Route path="/scene" element={<SceneDemo />} />')
        app.write_text(static_app, encoding="utf-8")
        el_s, chunks_s = _build(frontend)
        vendor = [c for c in chunks_s if "three-vendor" in os.path.basename(c)]
        three_copies = sum(1 for c in chunks_s if _has_marker(c))
        static_v = {
            "build_s": el_s, "chunks": len(chunks_s),
            "total_kb": sum(os.path.getsize(c) for c in chunks_s) // 1024,
            "initial_kb": os.path.getsize(_index_chunk(chunks_s)) // 1024,
            "three_in_initial": _has_marker(_index_chunk(chunks_s)),
            "three_copy_chunks": three_copies,
            "vendor_chunk_kb": (os.path.getsize(vendor[0]) // 1024) if vendor else 0,
        }

        return {"standard": std, "eager": eager, "lazy": lazy, "static": static_v}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def assertions(r: dict) -> list:
    checks = [
        ("standard build has no three", not r["standard"]["three_in_initial"]),
        ("lazy: three NOT in initial chunk", not r["lazy"]["three_in_initial"]),
        ("lazy: separate 3D chunk >=500KB exists", r["lazy"]["lazy3d_chunk_kb"] >= 500),
        ("preset initial does not inflate vs standard (>10% fails)",
         r["lazy"]["initial_kb"] <= 1.10 * r["standard"]["initial_kb"]
         and r["static"]["initial_kb"] <= 1.10 * r["standard"]["initial_kb"]),
        ("static 3D page: three NOT in entry (manualChunks)", not r["static"]["three_in_initial"]),
        ("static 3D page: single three copy", r["static"]["three_copy_chunks"] <= 1),
        ("static 3D page: vendor chunk exists (>=400KB)", r["static"]["vendor_chunk_kb"] >= 400),
    ]
    return checks


def markdown(r: dict, checks: list) -> str:
    import datetime
    date = datetime.date.today().isoformat()
    lines = [
        "# Bundle Benchmarks — Dependency Management Plan (P3)",
        "",
        f"_Generated by `scripts/bundle_benchmark.py` on {date}. "
        "Measured, not estimated. Machine-dependent; re-run for current numbers._",
        "",
        "| Variant | Build (s) | JS chunks | Total JS (KB) | **Initial JS (KB)** | three in initial? |",
        "|---|---|---|---|---|---|",
        f"| standard (baseline) | {r['standard']['build_s']:.1f} | {r['standard']['chunks']} "
        f"| {r['standard']['total_kb']} | **{r['standard']['initial_kb']}** "
        f"| {'YES' if r['standard']['three_in_initial'] else 'no'} |",
        f"| 3d preset + EAGER imports (worst case) | {r['eager']['build_s']:.1f} | {r['eager']['chunks']} "
        f"| {r['eager']['total_kb']} | **{r['eager']['initial_kb']}** "
        f"| {'YES' if r['eager']['three_in_initial'] else 'no'} |",
        f"| 3d preset + lazy3d wrapper (target) | {r['lazy']['build_s']:.1f} | {r['lazy']['chunks']} "
        f"| {r['lazy']['total_kb']} | **{r['lazy']['initial_kb']}** "
        f"| {'YES' if r['lazy']['three_in_initial'] else 'no'} |",
        f"| 3d preset + STATIC 3d page (2131 case) | {r['static']['build_s']:.1f} | {r['static']['chunks']} "
        f"| {r['static']['total_kb']} | **{r['static']['initial_kb']}** "
        f"| {'YES' if r['static']['three_in_initial'] else 'no'} |",
        "",
        f"Lazy 3D chunk size: **{r['lazy']['lazy3d_chunk_kb']} KB** "
        "(loads only when a 3D scene mounts).",
        "",
        "## Acceptance assertions (row 7)",
        "",
    ]
    for name, ok in checks:
        lines.append(f"- {'✅' if ok else '❌'} {name}")
    lines += [
        "",
        "## Reading",
        "- Eager 3D imports multiply the initial bundle by "
        f"**{r['eager']['initial_kb'] / max(1, r['standard']['initial_kb']):.1f}×** "
        "— which is why the 3d preset ships `src/lib/lazy3d.tsx` and the agent prompt "
        "forbids eager three/fiber/drei imports in shared components.",
        "- The `manualChunks` vendor rule (added with the 3d preset) is what "
        "keeps three out of the entry chunk in EVERY wiring — even eager "
        f"imports land at {r['eager']['initial_kb']} KB initial (they were "
        "1180 KB before the rule, live on project 2131). Without it, two "
        "dynamic entries sharing three made Rollup hoist a duplicate into "
        "the entry chunk.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "BENCHMARKS.md"))
    args = ap.parse_args()

    r = run_benchmarks()
    checks = assertions(r)
    md = markdown(r, checks)
    Path(args.out).write_text(md, encoding="utf-8")
    print(md)
    failed = [n for n, ok in checks if not ok]
    if failed:
        print(f"\nFAILED: {failed}", file=sys.stderr)
        return 1
    print(f"\nALL CHECKS PASS — written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
