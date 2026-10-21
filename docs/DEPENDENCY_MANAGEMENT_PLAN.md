# DreamAgent Intelligent Dependency Management — Implementation Plan (v2)

**Status:** PLANNING ONLY. **P0 is the only phase submitted for approval; P1–P3 require separate approval after P0 verification.**

## 1. Verified architecture facts (repo evidence)

| # | Fact | Evidence |
|---|---|---|
| F1 | `blank-template` is the ONLY website template (React 18.3.1, Vite 5.4.19, 48 deps, no 3D/animation libs); other templates Python-only | `fast_wrapper.py:37` hardcodes blank (Groq selection dead) |
| F2 | Creation rsync-copies template **including node_modules**; build **skips `npm ci` when node_modules exists** and **deletes it after verify** | `infrastructure_manager.py:2671-2675`, `2435-2451` |
| F3 | Redeploy = remove node_modules + `npm ci --prefer-offline --no-audit --legacy-peer-deps`; clone **excludes node_modules/dist**, `npm install`, cleanup | template buildpublish 86-145; `app.py:3809`, `4407-4421`, `3886-3898` |
| F4 | Container mode **already shares npm cache**: `NPM_CONFIG_CACHE=/cache/npm` ← `/srv/cache/npm` rw in every container; local mode uses root's `~/.npm` | `Dockerfile.user:131`; `container_manager.py:62-63`, `251-253` |
| F5 | Template **gitignores `package-lock.json`**, no committed lockfile → `npm ci` depends on worker disk state | template `.gitignore` |
| F6 | No AI path can change deps (prompts + path-blocks + editor allowlists); 3D brief today = failed build | `openclaw_wrapper.py:433`, `acp_frontend_editor_v2.py:57-69` |
| F7 | **No npm install gate** (pip has blocklist+MB-cap+shim); npm: egress allowlist + 200MB reply cap + write-time `check_package_json` only; local-mode npm runs as **root subprocess** | `file_utils.py:114-146` |
| F8 | Vite config minimal: no manualChunks, zero lazy/dynamic-import → single bundle; eager 3D would ship everywhere | template `vite.config.ts` |
| F9 | Static dist serving; template changes never mutate existing projects/deployed builds | nginx config |

**Assumptions to verify at implementation:** worker template disk actually holds node_modules/lockfile; `/srv/cache/npm` usable in local mode; container EXECUTION_MODE in production.

**Estimates requiring benchmarks (not claimed):** bundle sizes, install durations, disk deltas.

## 2. Phased roadmap (P0→P1→P2→P3)

### P0 — Reproducibility & observability (approval requested now)
1. Commit `package-lock.json` for blank-template; remove its `.gitignore` entry; creation-time invariant (lockfile present, `npm ci --dry-run` resolves).
2. Verify lockfile preserved through create/clone/redeploy; patch + test if not.
3. Formalize shared cache both modes: `NPM_CONFIG_CACHE=/srv/cache/npm` at all local install sites (3 in infrastructure_manager, template + root buildpublish, clone site); lockfiles/node_modules stay per-project.
4. Structured install logging: command, cwd, cache path, duration, exit code, node_modules size delta.
5. Zero behavior change for standard sites.
6. Rollback: drop lockfile + restore ignore + unset env; skip-install path unaffected.

### P1 — Secure dependency installation (approval after P0)
1. Sanctioned `add_frontend_deps(project_id, packages[])` backend service — the only dep-modification path.
2. Reuse `check_package_json` validation.
3. New npm gate (mirrors pip gate): allow/blocklist, **pinned versions required**, registry metadata + peer validation, per-op size cap, **fail closed** on unverifiable metadata, lifecycle-script ban, transitive-risk report.
4. Local-mode root-subprocess isolation proposal (container path or dedicated non-root build user) — decided at P1 review.
5. Unit + integration + adversarial tests before ship.

### P2 — Intelligent presets (approval after P1)
- `standard` (= today, byte-identical) / `animated` (+framer-motion) / `3D` (+three, fiber **v8 line**, drei **v9 line**; rapier/postprocessing only on brief demand — candidates pending React 18.3.1/Vite 5.4.19 peer verification via registry).
- Selection = brief classifier extending `phase8/planner.analyze_project_type`, **deterministic fallback standard**.
- Post-creation additions via P1 service only.
- Pre-seeded node_modules = optional optimization; **lockfile is source of truth**; cold `npm ci` must succeed.
- Zero mutation of existing projects.

### P3 — Bundle performance (approval after P2)
- Lazy 3D route (React.lazy+Suspense).
- Evaluate manualChunks (three in own chunk).
- Assert standard initial JS has no `three` via chunk manifest.
- Bundle-size/build-duration benchmarks — baseline first, thresholds only after stability.

## 3. Candidate files (pending verification)

| Phase | Files |
|---|---|
| P0 | template `.gitignore`/new lockfile; `infrastructure_manager` 3 npm sites; template+root buildpublish env; clone site; deploy scripts |
| P1 | new `services/sandbox/npm_gate.py`; new deps service; `file_utils` expose check |
| P2 | `templates/presets/{standard,animated,3d}/`; `fast_wrapper`; `project_creation_runs`; `planner` |
| P3 | preset vite configs; `tests/benchmarks/` |

## 4. Risk register

| Risk | Severity | Mitigation | Verification |
|---|---|---|---|
| Lockfile commit breaks rsync | Med | measure size | P0 tests |
| Cache contention | Low | npm cache concurrency-safe by design | concurrent test |
| Gate fail-closed blocks builds | Med | log-only rollout + admin escape | adversarial tests |
| Preset peer incompat | Med | registry peer check | install test |
| Pre-seed drift | Med | lockfile authoritative + dry-run invariant | cold-install test |
| Classifier misroute | Low | P1 service recovers | risk row 6 |
| Root npm risk | High | P1 isolation decision | design review |
| Standard bundle regression | Med | P3 baseline+gates | risk row 7 |

## 5. Acceptance criteria / test matrix

| # | Criterion | Phase(s) |
|---|---|---|
| 1 | Standard deps byte-identical | P0, P2 |
| 2 | Lockfile survives create/clone/redeploy hash-compared | P0 |
| 3 | Concurrent installs keep separate lockfiles+node_modules | P0 |
| 4 | Cache hits improve repeat installs, no contamination | P0 |
| 5 | Unsafe/oversized/unpinned/unverifiable rejected, fail-closed proven | P1 |
| 6 | 3D project gets exactly preset deps | P2 |
| 7 | Standard initial JS contains no three; bundle unchanged vs baseline | P3 |
| 8 | Existing projects+dist hash-unchanged | P2, P3 |
| 9 | Failures logged + rehearsed rollback | P0+ |

## 6. Rollback & release strategy

- **P0 revert:** drop lockfile / restore ignore / unset env (skip-install path untouched, flagless release).
- **P1 ships:** `NPM_GATE_ENFORCE=0` log-only until adversarial pass; flip env to roll back.
- **P2:** additive, force-standard fallback.
- **P3:** per-preset config revert.
- **Order:** P0 → 1 week logs → P1 log-only → enforce → P2 → P3.

## 7. Approval boundary

**Approving this plan = approving (a) writing this document to `docs/DEPENDENCY_MANAGEMENT_PLAN.md` and (b) the P0 design for a FUTURE implementation task.** No phase is implemented now; P1–P3 need explicit separate approvals.

---

## Addendum (P0 review): shared-cache growth watch

Per review feedback, `run_npm()` and the template `buildpublish.py` also log
**`cache_delta` and `cache_total`** (`/srv/cache/npm` usage before/after every
install). If the logs show unbounded growth across projects, the follow-up is
an `npm cache clean --force` cron or a size cap — decide from the collected
data, not preemptively. (Implemented with P0.)
