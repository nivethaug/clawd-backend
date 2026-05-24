# Context API Wrapper for Claude Code - Dream Agent Create/Edit Support Report

> Scope date: 2026-05-20  
> Related files reviewed:
> - `D:\clawduiback\clawd-backend\app.py`
> - `D:\clawduiback\clawd-backend\acp_chat_handler.py`
> - `D:\clawduiback\clawd-backend\codex_code_agent.py`
> - `D:\claudewrapper\context_api.py`
> - `D:\clawduiback\clawd-backend\docs\toc.md`
> - `D:\clawduiback\clawd-backend\docs\project_creation.md`
> - `D:\clawduiback\clawd-backend\docs\chat_stream.md`

---

## 1) Executive Summary

The current stack already has strong building blocks for Dream Agent project workflows:

1. Project/session lifecycle is implemented in backend APIs (`/projects`, `/sessions`, `/chat/stream`).
2. ACP handler supports multi-project-type prompt routing (website, telegram, discord, scheduler).
3. Wrapper guardrails in `context_api.py` now distinguish create vs edit better than before.

Main issue today is not missing infrastructure. It is behavioral drift during edit loops:

1. Verification/checklist logic can still over-constrain edits in some paths.
2. Runtime-port and target URL assumptions can be stale (`localhost:3000` style drift).
3. Forced exploration patterns can still trigger repeated read/search cycles when the model should perform direct error repair.

---

## 2) Current Architecture (How Requests Flow)

## A. Backend entrypoints

- `app.py` provides project/session/chat endpoints and persistence.
- `POST /chat/stream` is the primary interactive path.
- ACP mode is default-enabled for frontend editing (`acp_mode=True` in request model).

## B. ACP orchestration

- `acp_chat_handler.py` creates/returns per-session handlers.
- It builds project-type-specific prompts.
- It runs unified streaming:
  - Preferred backend: `ClaudeCodeAgent` (direct CLI flow).
  - Fallback: ACPX stream mode.

## C. Wrapper behavior (Anthropic-compatible)

- `D:\claudewrapper\context_api.py` is the policy/guard layer around tool-calling.
- It performs:
  - argument sanitation and path normalization
  - completion gating and forced verification tool calls
  - repair hint injection
  - token metrics and tool-result windowing
  - fallback between Tier 1 and Tier 2 providers

---

## 3) Session & History Model (Current)

## Backend session history

1. User/assistant messages are persisted in DB per `session_id`.
2. `chat/stream` loads a limited recent context window for prompt conditioning.
3. `last_used_at` is updated on assistant save.
4. Session lock service enforces one active editing session per project.

## Agent-side continuity

1. `acp_chat_handler.py` keeps module-level `_claude_session_ids` keyed by `repo_path` for resume continuity.
2. This allows repeated chats in same project path to reuse session identity where supported by underlying agent.
3. `codex_code_agent.py` explicitly states one-shot execution semantics; resume field is currently interface parity, not full multi-turn session replay.

## Wrapper history impact

1. Wrapper scans recent tool-use/tool-result windows and injects hints/tool-calls.
2. Long iterative loops can inflate tool-result history token footprint if guardrails keep re-triggering.

---

## 4) Dream Agent Create vs Edit Support - Current State

## What works well now

1. Live edit workflow detection exists in wrapper and influences hints.
2. Buildpublish-aware enforcement exists (`python3 buildpublish.py` for website edit flow).
3. Completion gate and repair-hint systems are implemented and instrumented.
4. English-only output enforcement path exists in wrapper for final text normalization.

## What still causes friction

1. Edit runs can still get pulled into non-error-driven exploration (read/glob/semantic search loops).
2. Health-check target inference is not yet guaranteed to be canonical project runtime target every turn.
3. Completion blockers can still trigger retry loops when evidence signals are partial/noisy.
4. Some docs still describe older file/line mappings or mixed legacy paths, which can confuse agent navigation.

---

## 5) High-Priority Gaps to Fully Support Dream Agent

## P0 - Stop edit-loop drift completely

1. Keep edit-mode forcing strictly error-driven:
   - only act on concrete failing command/tool result
   - avoid broad semantic exploration forcing when a hard failure is present
2. Add loop breaker for repeated identical failure signature:
   - detect same failed command + same exit code + same output hash repeated N times
   - escalate with deterministic fallback action (port discovery/log command), then stop reinjecting same hint

## P0 - Canonical runtime target resolution

1. Maintain a single resolved “active target URL/port” per task window.
2. Use that value consistently across:
   - repair hints
   - curl checks
   - browser verification commands
3. If unresolved, run one deterministic discovery command and store result before further hints.

## P1 - Completion gate strategy split by intent

1. Create intent:
   - keep strong checklist (multi-page, build, serve/publish, browser pass).
2. Edit intent:
   - require only “failure resolved + verification command re-run success”.
   - do not require create-style multi-page thresholds.

## P1 - Evidence quality hardening

1. Distinguish “tool executed” from “tool produced actionable output”.
2. Prevent empty/no-output Bash completions from counting as progress.
3. Track positive completion evidence with stronger markers (build success lines, HTTP 200, browser pass true).

## P2 - Observability for operator debugging

1. Emit structured guard decision summary per turn:
   - mode=create/edit
   - selected target URL/port
   - last failure signature
   - forced action reason
2. Add counters for repeated-hint suppression and loop-break triggers.

---

## 6) Suggested Implementation Plan

## Phase 1 (Immediate, low risk)

1. Add repeated-failure signature cache in `context_api.py`.
2. Add canonical target resolver and reuse it in all hint templates.
3. Suppress identical hint injection after first repeat unless new evidence appears.

## Phase 2 (Behavior refinement)

1. Harden edit completion logic:
   - success = fail command resolved + one verification pass
2. Reduce exploration forcing in edit mode even further.
3. Add guard test fixtures from real logs (including `curl exit 7`, empty PM2 error logs, missing route).

## Phase 3 (Doc + DX alignment)

1. Update docs to point to authoritative active files/paths.
2. Add “create vs edit policy matrix” doc section for operators.
3. Add runbook commands for common failures.

---

## 7) Suggested Acceptance Criteria (Dream Agent Fully Supported)

1. For edit tasks with runtime failures, median turns-to-first-fix drops significantly (target < 8 turns).
2. Repeated identical repair hint appears at most once per unchanged failure signature.
3. No create-style multi-page blocker appears in edit-only tasks.
4. Browser verification checks use resolved project target (not hardcoded default ports).
5. Final responses remain English-only in enforced mode.

---

## 8) Practical Notes for Current UI Project Types

Given project types shown in Create Project dialog (Website, Telegram Bot, Discord Bot, Trading Bot, Scheduler, Custom):

1. Website should use create/edit split rules already present in wrapper and ACP prompts.
2. Telegram/Discord/Scheduler flows should remain primarily command/runtime-state-driven and avoid website-specific page-stub heuristics.
3. Custom/Trading-bot type should default to generic error-driven edit policy until specialized verifier profile exists.

---

## 9) Recommended Next Changes (Concrete)

1. Add `failure_signature = hash(command + exit_code + normalized_output)` and hint dedupe logic.
2. Add `resolve_active_target(raw_messages, frontend_cwd)` and use everywhere hints/curl/browser are generated.
3. Gate Semble/exploration forcing behind `not live_edit_workflow` and `no hard failure present`.
4. Add unit tests for:
   - edit loop with same curl failure repeating
   - target URL inference precedence
   - no create checklist leakage into edit.

---

## 10) Conclusion

The platform is close. Core plumbing is solid, and your recent guard split direction is correct.  
To fully support Dream Agent create/edit flows, focus on deterministic edit-loop control, canonical target resolution, and strict hint deduplication tied to failure signatures.

