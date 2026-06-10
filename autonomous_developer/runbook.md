# Codex Maintainer — Runbook

> Operations manual for the autonomous Codex maintenance agent.

---

## Quick Reference

| What | Command |
|------|---------|
| **Run manually** | `python autonomous_developer/codex_maintainer.py` |
| **Run via cron entry** | `python autonomous_developer/codex_cron.py` |
| **Check usage state** | `cat autonomous_developer/data/codex_usage_state.json` |
| **Check logs** | `cat autonomous_developer/data/codex_maintainer.log` |
| **Check cron logs** | `cat autonomous_developer/data/codex_cron.log` |
| **Force reset usage** | See [Force Reset](#force-reset) below |
| **Clear stale lock** | `rm autonomous_developer/data/codex_maintainer.lock` |
| **Register Task Scheduler** | See [Task Scheduler Setup](#task-scheduler-setup) |

---

## Architecture

```
Task Scheduler (5 min) → codex_cron.py
    │
    ├─ Usage OK? ──→ codex_maintainer.py
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

## File Locations

| File | Path |
|------|------|
| Package root | `clawd-backend/autonomous_developer/` |
| Maintainer script | `autonomous_developer/codex_maintainer.py` |
| Cron runner | `autonomous_developer/codex_cron.py` |
| Usage tracker | `autonomous_developer/codex_usage_tracker.py` |
| Configuration | `autonomous_developer/config.py` |
| State file | `autonomous_developer/data/codex_usage_state.json` |
| Lock file | `autonomous_developer/data/codex_maintainer.lock` |
| Maintainer log | `autonomous_developer/data/codex_maintainer.log` |
| Cron log | `autonomous_developer/data/codex_cron.log` |

---

## Manual Operations

### Run the Maintainer Once

```bash
cd D:\clawduiback\clawd-backend
d:\clawduiback\.venv\Scripts\python.exe autonomous_developer/codex_maintainer.py
```

### Run via Cron Entry Point (includes guards)

```bash
cd D:\clawduiback\clawd-backend
d:\clawduiback\.venv\Scripts\python.exe autonomous_developer/codex_cron.py
```

### Check Current Usage

```bash
# Pretty-print state file
python -c "import json; print(json.dumps(json.load(open('autonomous_developer/data/codex_usage_state.json')), indent=2))"
```

### Force Reset

If you need to manually reset the usage counter (e.g., after debugging):

```bash
python -c "
import json
from datetime import datetime, timezone
state = {
    'total_seconds_used': 0,
    'limit_seconds': 18000,
    'limit_hours': 5,
    'current_run_start': None,
    'paused': False,
    'last_reset': datetime.now(timezone.utc).isoformat(),
    'reset_interval_hours': 24
}
with open('autonomous_developer/data/codex_usage_state.json', 'w') as f:
    json.dump(state, f, indent=2)
print('Usage state reset successfully')
"
```

Or simply delete the state file and it will be recreated with defaults:

```bash
rm autonomous_developer/data/codex_usage_state.json
```

### Clear Stale Lock

If the maintainer crashed without cleaning up:

```bash
rm autonomous_developer/data/codex_maintainer.lock
```

The cron runner also auto-detects stale locks older than 30 minutes.

---

## Task Scheduler Setup (Windows)

### Using PowerShell (recommended)

```powershell
$action = New-ScheduledTaskAction `
    -Execute "d:\clawduiback\.venv\Scripts\python.exe" `
    -Argument "D:\clawduiback\clawd-backend\autonomous_developer\codex_cron.py" `
    -WorkingDirectory "D:\clawduiback\clawd-backend"

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 365)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -DontStopOnIdleEnd

Register-ScheduledTask `
    -TaskName "CodexMaintainer" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Autonomous Codex maintenance agent — runs every 5 minutes" `
    -RunLevel Highest
```

### Using schtasks (simpler)

```powershell
schtasks /create /tn "CodexMaintainer" /tr "d:\clawduiback\.venv\Scripts\python.exe D:\clawduiback\clawd-backend\autonomous_developer\codex_cron.py" /sc minute /mo 5 /ru SYSTEM
```

### Verify Task Registration

```powershell
Get-ScheduledTask -TaskName "CodexMaintainer" | Format-List
```

### Remove Task

```powershell
Unregister-ScheduledTask -TaskName "CodexMaintainer" -Confirm:$false
```

---

## Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `QA_DB_PATH` | `D:\clawduiback\ai-qa-tester\qa_tester.db` | Path to QA tester SQLite DB |
| `WRAPPER_PATH` | `D:\claudewrapper\context_api.py` | Path to wrapper file Codex edits |
| `CODEX_REPO_PATH` | `D:\claudewrapper` | Repo path for Codex agent |
| `CODEX_TIMEOUT` | `600` | Codex query timeout (seconds) |
| `PM2_PROCESS` | `clawd-backend` | PM2 process name to restart |
| `BACKEND_URL` | `http://localhost:8000` | Backend API base URL |
| `WRAPPER_HEALTH_URL` | `http://localhost:7861/health` | Wrapper health check URL |
| `POLL_INTERVAL` | `12` | Status poll interval (seconds) |
| `PROJECT_TIMEOUT` | `600` | Max wait for project completion |
| `MAX_ITERATIONS` | `10` | Safety cap per run |
| `USAGE_LIMIT_HOURS` | `5` | Daily Codex usage limit |
| `RESET_INTERVAL_HOURS` | `24` | Hours before usage resets |
| `TELEGRAM_BOT_TOKEN` | _(empty)_ | Telegram notifications |
| `TELEGRAM_CHAT_ID` | _(empty)_ | Telegram chat ID |
| `DISCORD_WEBHOOK_URL` | _(empty)_ | Discord webhook URL |

---

## Troubleshooting

### Maintainer not running

1. Check cron log: `cat autonomous_developer/data/codex_cron.log`
2. Is Task Scheduler task registered? `Get-ScheduledTask -TaskName "CodexMaintainer"`
3. Is a lock file stuck? Check `autonomous_developer/data/codex_maintainer.lock` age

### "Usage limit reached" but should be reset

See [Force Reset](#force-reset) above.

### PM2 restart fails

```bash
# Check PM2 status
pm2 list

# Manual restart
pm2 restart clawd-backend

# Check PM2 logs
pm2 logs clawd-backend --lines 50
```

### Codex CLI not found

Ensure `codex` is in the system PATH. The `CodexCodeAgent` searches:
- `shutil.which("codex")`
- Common paths: `/usr/local/bin/codex`, `~/.local/bin/codex`, etc.
- Or set `codex_path` in `~/.codex/settings.json`

### Test project creation fails

1. Is the backend running? `curl http://localhost:8000/docs`
2. Check backend logs: `pm2 logs clawd-backend`
3. Verify the API: `curl -X POST http://localhost:8000/projects -H "Content-Type: application/json" -d '{"name":"test","description":"test","user_id":1,"type_id":1,"template_id":"blank-template"}'`

### Wrapper health check fails

1. Is the wrapper process running? `curl http://localhost:7861/health`
2. Check if PM2 started it: `pm2 list`
3. Review wrapper logs for startup errors

---

## Codex Prompt Templates

### General Fix Prompt

```
Fix the issue in context_api.py.

## Failure Details
- Project ID: {id}
- Domain: {domain}
- Issues: {issues}

## Instructions
1. Read context_api.py
2. Identify root cause
3. Make minimal fix
4. Preserve all API contracts
```

### Timeout Fix Prompt

```
The wrapper is timing out when processing projects.

Check context_api.py for:
- Infinite loops or blocking calls
- Missing timeouts on external requests
- Deadlock-prone patterns

Fix and ensure all operations have proper timeouts.
```

### Import Error Fix Prompt

```
context_api.py is failing with import errors.

Check:
- All imports resolve correctly
- No circular dependencies
- Required packages are available

Fix import paths and ensure clean startup.
```

---

## Safety Guards Summary

| Guard | Mechanism | Limit |
|-------|-----------|-------|
| Concurrent runs | Lock file (`codex_maintainer.lock`) | 1 at a time |
| Loop iterations | `MAX_ITERATIONS` | 10 per run |
| Subprocess timeout | `MAX_SUBPROCESS_TIMEOUT` | 20 minutes |
| Daily usage | `CodexUsageTracker` | 5 hours / 24h |
| Stale lock detection | Lock file age check | 30 minutes |
| PM2 scope | Process name filter | `clawd-backend` only |
| Agent isolation | No production imports | Codex only in maintainer/tests |

---

## Monitoring Checklist

- [ ] Cron log shows 5-minute ticks
- [ ] Usage state file is being updated
- [ ] Maintainer log shows fix attempts
- [ ] PM2 `clawd-backend` stays online
- [ ] Wrapper health endpoint responds
- [ ] Telegram/Discord notifications fire on critical events
- [ ] No `CodexCodeAgent` imports in production code
