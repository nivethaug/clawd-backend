# Codex Maintainer — Master Plan

> **Codex is the external autonomous maintenance agent.  
> ClaudeCodeAgent stays in production for all 7 user-facing DreamAgent flows.  
> Codex NEVER touches production paths.**

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   System Crontab                     │
│              */5 * * * * codex_cron.py                │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              codex_cron.py (Entry Point)             │
│  • Check usage guard (5h limit)                      │
│  • If usage OK → spawn codex_maintainer.py           │
│  • If usage hit → log, exit, wait for reset          │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│           codex_maintainer.py (Main Loop)            │
│                                                      │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ 1. Read   │  │ 2. Codex  │  │ 3. Restart PM2   │  │
│  │    QA     │→ │    Edit   │→ │    (wrapper)      │  │
│  │ Failures  │  │ context_  │  └────────┬─────────┘  │
│  └──────────┘  │ api.py    │           │             │
│                 └───────────┘           ▼             │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ 6. Loop  │← │ 5. Validate│←│ 4. Create Test   │  │
│  │ until    │  │    Logs    │  │    Project       │  │
│  │ success  │  └───────────┘  └──────────────────┘  │
│  └──────────┘                                        │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│           codex_usage_tracker.py (Parallel)          │
│  • Monitor Codex API usage                           │
│  • Pause at 5-hour target                            │
│  • Resume after reset window                         │
│  • Expose status file for cron guard                 │
└─────────────────────────────────────────────────────┘
```

---

## 2. File Inventory

| File | Location | Purpose |
|------|----------|---------|
| Codex Maintainer | `scripts/codex_maintainer.py` | Autonomous edit→test→fix loop |
| Usage Tracker | `scripts/codex_usage_tracker.py` | API usage monitoring + guard |
| Cron Runner | `scripts/codex_cron.py` | Crontab entry point (5-min interval) |
| Runbook | `docs/codex_runbook.md` | Developer operations manual |
| CodexCodeAgent | `codex_code_agent.py` | Existing — Codex CLI wrapper (no changes) |

---

## 3. Phase 1 — Codex Maintainer Script

### File: `scripts/codex_maintainer.py`

**Purpose:** Runs the autonomous edit→test→fix loop.

**Architecture (mirrors `ai-qa-tester`):**

```
maintainer_loop():
    while not all_passed:
        failures = read_recent_failures()       # From wrapper logs / QA DB
        if no_failures:
            log("All clear")
            break

        for failure in failures:
            # Step 1: Codex edits context_api.py
            codex_fix(failure)

            # Step 2: Restart PM2 wrapper
            restart_pm2("clawd-backend")

            # Step 3: Create test project via API
            project_id = create_test_project(failure.description)

            # Step 4: Poll status until complete
            result = poll_project_status(project_id, timeout=600)

            # Step 5: Validate wrapper logs
            logs_valid = validate_wrapper_logs(project_id)

            if result.success and logs_valid:
                mark_fixed(failure)
            else:
                log_retry(failure, result)
                continue  # Loop retries

        # Safety: max iterations
        if iterations >= MAX_ITERATIONS:
            notify("Max iterations reached — manual intervention needed")
            break
```

**Key Components:**

| Component | Implementation | Source Reference |
|-----------|---------------|------------------|
| Failure reader | Parse `qa_tester.db` + wrapper logs | `storage.py::get_active_projects()` |
| Codex fix call | `CodexCodeAgent.query(prompt)` | `codex_code_agent.py` |
| PM2 restart | `subprocess.run(["pm2", "restart", "clawd-backend"])` | PM2 ecosystem |
| Test project creation | `POST /projects` with test payload | `project_client.py` |
| Status polling | `GET /projects/{id}/status` loop, 12s interval | `project_client.py` |
| Log validation | Parse wrapper logs for error signatures | `_failure_signature()` in context_api.py |
| Notifications | Telegram/Discord webhook | `notifier.py` |

**Config Constants:**
```python
MAX_ITERATIONS = 10          # Safety cap per run
POLL_INTERVAL = 12           # Seconds between status checks (matches QA tester)
PROJECT_TIMEOUT = 600        # Max seconds to wait for project completion
CLAUDE_TIMEOUT = 600         # Codex query timeout
WRAPPER_PATH = r"D:\claudewrapper\context_api.py"
PM2_PROCESS = "clawd-backend"
BACKEND_URL = "http://localhost:8000"
WRAPPER_HEALTH_URL = "http://localhost:7861/health"
```

---

## 4. Phase 2 — Usage Tracker

### File: `scripts/codex_usage_tracker.py`

**Purpose:** Monitor Codex API usage, pause before hitting 5-hour limit, resume after reset.

**State File:** `scripts/data/codex_usage_state.json`
```json
{
  "total_seconds_used": 12345,
  "limit_seconds": 18000,
  "limit_hours": 5,
  "current_run_start": null,
  "paused": false,
  "last_reset": "2026-06-01T00:00:00Z",
  "reset_interval_hours": 24
}
```

**Logic:**
```python
class CodexUsageTracker:
    def __init__(self, state_file):
        self.state = load_json(state_file)
    
    def can_proceed(self) -> bool:
        """Check if usage is within limits."""
        if self.state["paused"]:
            if self.reset_window_passed():
                self.reset_usage()
                return True
            return False
        return self.state["total_seconds_used"] < self.state["limit_seconds"]
    
    def record_start(self):
        """Mark beginning of a Codex session."""
        self.state["current_run_start"] = utcnow()
        save_json(self.state)
    
    def record_end(self):
        """Record seconds used and clear run start."""
        elapsed = (utcnow() - self.state["current_run_start"]).total_seconds()
        self.state["total_seconds_used"] += elapsed
        self.state["current_run_start"] = None
        
        if self.state["total_seconds_used"] >= self.state["limit_seconds"]:
            self.state["paused"] = True
        
        save_json(self.state)
    
    def reset_window_passed(self) -> bool:
        """Check if 24h reset window has elapsed."""
        last = parse_datetime(self.state["last_reset"])
        return (utcnow() - last) >= timedelta(hours=self.state["reset_interval_hours"])
    
    def reset_usage(self):
        """Reset usage counter after reset window."""
        self.state["total_seconds_used"] = 0
        self.state["paused"] = False
        self.state["last_reset"] = utcnow().isoformat()
        save_json(self.state)
    
    def remaining_hours(self) -> float:
        """Return remaining hours before limit."""
        remaining = self.state["limit_seconds"] - self.state["total_seconds_used"]
        return max(0, remaining / 3600)
```

**Integration with Maintainer:**
- Before each Codex call: `tracker.can_proceed()` — if False, exit gracefully
- On Codex session start: `tracker.record_start()`
- On Codex session end: `tracker.record_end()`
- Cron reads state file to decide whether to spawn maintainer

---

## 5. Phase 3 — Cron Runner

### File: `scripts/codex_cron.py`

**Purpose:** System crontab entry point. Guards usage, spawns maintainer.

```python
#!/usr/bin/env python3
"""
Codex Cron Runner — invoked by system crontab every 5 minutes.
Usage: python scripts/codex_cron.py
"""
import sys, subprocess, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from codex_usage_tracker import CodexUsageTracker

LOCK_FILE = Path(__file__).parent / "data" / "codex_maintainer.lock"
STATE_FILE = Path(__file__).parent / "data" / "codex_usage_state.json"
LOG_FILE = Path(__file__).parent / "data" / "codex_cron.log"

def main():
    logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    
    # Guard 1: Already running?
    if LOCK_FILE.exists():
        logging.warning("Maintainer already running — skipping")
        return 0
    
    # Guard 2: Usage limit check
    tracker = CodexUsageTracker(STATE_FILE)
    if not tracker.can_proceed():
        remaining = tracker.remaining_hours()
        logging.info(f"Usage limit reached. Remaining: {remaining:.1f}h (paused={tracker.state['paused']})")
        return 0
    
    # Spawn maintainer
    try:
        LOCK_FILE.touch()
        logging.info("Spawning codex_maintainer.py")
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "codex_maintainer.py")],
            capture_output=True, text=True, timeout=1200  # 20-min max
        )
        logging.info(f"Maintainer exited: code={result.returncode}")
        if result.stderr:
            logging.error(f"stderr: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        logging.error("Maintainer timed out after 20 minutes")
    except Exception as e:
        logging.error(f"Maintainer failed: {e}")
    finally:
        LOCK_FILE.unlink(missing_ok=True)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

**Crontab Entry (Windows Task Scheduler equivalent):**
```xml
<!-- Task Scheduler: codex-maintainer, every 5 minutes -->
<Trigger>
  <IntervalTrigger>
    <Repetition>
      <Interval>PT5M</Interval>
      <Enabled>true</Enabled>
    </Repetition>
  </IntervalTrigger>
</Trigger>
<Actions>
  <Exec>
    <Command>d:\clawduiback\.venv\Scripts\python.exe</Command>
    <Arguments>D:\clawduiback\clawd-backend\scripts\codex_cron.py</Arguments>
    <WorkingDirectory>D:\clawduiback\clawd-backend</WorkingDirectory>
  </Exec>
</Actions>
```

**Or via schtasks (PowerShell):**
```powershell
schtasks /create /tn "CodexMaintainer" /tr "d:\clawduiback\.venv\Scripts\python.exe D:\clawduiback\clawd-backend\scripts\codex_cron.py" /sc minute /mo 5 /ru SYSTEM
```

---

## 6. Phase 4 — Runbook

### File: `docs/codex_runbook.md`

**Contents:**
- How to start/stop the maintainer manually
- How to check usage state
- How to force a reset
- Troubleshooting guide
- Lock file cleanup procedure
- PM2 restart verification steps
- Codex prompt templates for common failure patterns

---

## 7. Phase 5 — Agent Isolation Verification

**Ensure no production path uses Codex:**

| Check | Expected | Method |
|-------|----------|--------|
| `CodexCodeAgent` imports | Only in `tests/` | `grep -r "codex_code_agent" --include="*.py"` |
| `codex` CLI calls | Only in maintainer + tests | `grep -r "codex" --include="*.py"` |
| Maintainer touches `context_api.py` | Only via Codex, never Claude | Code review |
| PM2 restart scope | Only wrapper | Verify process name |
| Cron user | SYSTEM or dedicated service account | Task Scheduler config |

---

## 8. Data Flow Summary

```
Cron (5min) → codex_cron.py
                │
                ├─ Usage OK? ──→ codex_maintainer.py
                │                    │
                │                    ├─ Read failures from qa_tester.db
                │                    ├─ CodexCodeAgent.query("fix X in context_api.py")
                │                    ├─ pm2 restart clawd-backend
                │                    ├─ POST /projects (create test)
                │                    ├─ Poll status (12s interval)
                │                    ├─ Validate wrapper logs
                │                    └─ Loop until all pass or MAX_ITER
                │
                └─ Usage hit? ──→ Log + exit (wait for reset)
```

---

## 9. Dependencies

- `codex_code_agent.py` (existing, no changes)
- `ai-qa-tester/storage.py` patterns (reference, not import)
- `ai-qa-tester/project_client.py` patterns (reference, not import)
- PM2 CLI (`pm2 restart`)
- Python 3.10+ (matches existing)
- `aiosqlite` (for reading QA tester DB)
- `httpx` (for API calls)
- Standard library: `subprocess`, `json`, `logging`, `pathlib`, `datetime`

---

## 10. Implementation Order

| Step | File | Depends On | Est. Lines |
|------|------|------------|------------|
| 1 | `scripts/codex_usage_tracker.py` | None | ~120 |
| 2 | `scripts/codex_maintainer.py` | Usage tracker | ~350 |
| 3 | `scripts/codex_cron.py` | Both above | ~80 |
| 4 | `docs/codex_runbook.md` | All scripts | ~150 |
| 5 | Task Scheduler registration | cron script | N/A |

---

## 11. Safety Guards

1. **Lock file** prevents concurrent maintainer runs
2. **MAX_ITERATIONS=10** caps loops per cron invocation
3. **20-minute timeout** on maintainer subprocess
4. **Usage tracker** enforces 5-hour daily limit
5. **PM2 restart** only targets `clawd-backend` (not scheduler)
6. **Health check** after restart: `GET http://localhost:7861/health`
7. **Agent isolation**: Codex never imported in production paths
8. **Rollback**: Codex edits are git-trackable in `D:\claudewrapper`

---

## 12. Success Criteria

- [ ] Codex maintainer reads failures, fixes context_api.py, restarts PM2, validates
- [ ] Test project creation succeeds via API after fixes
- [ ] Wrapper logs show no error signatures after fix
- [ ] Usage tracker correctly pauses at 5-hour limit
- [ ] Usage tracker resumes after 24-hour reset window
- [ ] Cron runner spawns maintainer every 5 minutes when usage allows
- [ ] Lock file prevents concurrent runs
- [ ] No production code path imports or calls CodexCodeAgent
- [ ] All notifications (Telegram/Discord) fire on critical events
