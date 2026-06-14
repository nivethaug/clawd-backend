# Token Usage Tracking — Migration & Wiring Plan

## Goal

Every Claude Code query (create + edit, all project types) must store real token usage + cost into the `token_usage` table after completion.

---

## 1. Database Migration: Add `cost_usd` Column

**Table:** `token_usage`
**Migration type:** Non-destructive `ALTER TABLE ... ADD COLUMN`

```sql
ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(12,6) DEFAULT 0;
```

### Migration Location

File: `database_postgres.py` → in the migrations block after the `token_usage` table creation (~line 558+).

```python
def migrate_token_usage_cost():
    cur.execute(
        "ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(12,6) DEFAULT 0"
    )
    logger.info("✓ Added cost_usd column to token_usage table")
_run_migration(migrate_token_usage_cost)
```

### Updated Table Schema

```sql
CREATE TABLE token_usage (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id      INTEGER,
    session_id      INTEGER,
    usage_type      VARCHAR(30) NOT NULL,     -- ai_chat | project_create | ai_completion
    description     TEXT,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    model           VARCHAR(100),
    cost_usd        NUMERIC(12,6) DEFAULT 0,   -- ← NEW
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 2. Update `token_tracker.py`

### `record_usage()` — Add `cost_usd` parameter

```python
def record_usage(
    user_id: int,
    usage_type: str,
    total_tokens: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,           # ← NEW
    project_id: Optional[int] = None,
    ...
) -> bool:
```

SQL change:
```python
INSERT INTO token_usage
   (user_id, project_id, session_id, usage_type, description,
    input_tokens, output_tokens, total_tokens, model, cost_usd)   -- ← add cost_usd
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)                   -- ← add %s
```

### `record_from_token_usage_json()` — Extract `cost_usd`

```python
cost = token_usage_json.get("cost_usd") or token_usage_json.get("costUsd") or 0.0

return record_usage(
    ...,
    cost_usd=float(cost),   # ← pass through
)
```

---

## 3. Wiring: Every Query Completion → `token_usage` Table

### Already wired (no change needed)

| Path | Where it's called | Status |
|------|-------------------|--------|
| Chat/Edit streaming | `app.py:3072` → `record_from_token_usage_json()` | ✅ Works |
| Chat/Edit non-streaming | `app.py:3622` → `record_from_token_usage_json()` | ✅ Works |

### Needs wiring

| Path | File | Editor Class | `user_id` available? | `project_id` available? |
|------|------|-------------|---------------------|----------------------|
| Website create | `acp_frontend_editor_v2.py` | `ACPXV2Editor` (has `self.project_id`) | ❌ Needs DB lookup | ✅ `self.project_id` |
| Telegram create | `services/telegram/worker.py` | `TelegramBotEditor` | ❌ Needs DB lookup | ✅ `project_id` param |
| Discord create | `services/discord/worker.py` | `DiscordBotEditor` | ❌ Needs DB lookup | ✅ `project_id` param |
| Scheduler create | `services/scheduler/worker.py` | `SchedulerEditor` | ❌ Needs DB lookup | ✅ `project_id` param |

### Pattern for workers (telegram/discord/scheduler)

After `editor.enhance_bot_logic()` / `editor.enhance_executor()` returns:

```python
# Record token usage
try:
    from services.token_tracker import record_from_token_usage_json
    usage = getattr(editor, '_last_token_usage', None)
    if usage:
        # Look up user_id from project
        from database_adapter import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT user_id FROM projects WHERE id = %s", (project_id,)
            ).fetchone()
        user_id = row["user_id"] if row else None
        if user_id:
            record_from_token_usage_json(
                user_id=user_id,
                token_usage_json=usage,
                usage_type="project_create",
                project_id=project_id,
                description=f"Telegram bot create: {project_name}",
            )
except Exception as track_err:
    logger.warning(f"Token tracking failed: {track_err}")
```

### Pattern for website create

In `acp_frontend_editor_v2.py` after `agent.query()` returns (inside `_run_claude_agent`):

```python
self._last_token_usage = agent.last_token_usage

# Record to token_usage table
try:
    from services.token_tracker import record_from_token_usage_json
    from database_adapter import get_db
    if self._last_token_usage and self.project_id:
        with get_db() as conn:
            row = conn.execute(
                "SELECT user_id FROM projects WHERE id = %s", (self.project_id,)
            ).fetchone()
        user_id = row["user_id"] if row else None
        if user_id:
            record_from_token_usage_json(
                user_id=user_id,
                token_usage_json=self._last_token_usage,
                usage_type="project_create",
                project_id=self.project_id,
                description=f"Website create: {self.project_name}",
            )
except Exception as track_err:
    logger.warning(f"[ACPX-V2] Token tracking failed: {track_err}")
```

---

## 4. Verification Checklist

After deployment, verify:

```sql
-- Check cost_usd column exists
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'token_usage' AND column_name = 'cost_usd';

-- Check recent entries (after a create/edit query)
SELECT id, usage_type, input_tokens, output_tokens, cost_usd, model, created_at
FROM token_usage
ORDER BY created_at DESC
LIMIT 10;

-- Check all project types are tracked
SELECT usage_type, COUNT(*), SUM(cost_usd)
FROM token_usage
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY usage_type;
```

---

## 5. Cost Source

Cost is calculated **client-side in the wrapper** (`model_adapter.py` pricing table).
The wrapper returns `cost_usd` in its `/usage/session/{id}` endpoint totals.
The backend's `_fetch_usage_session()` stores it in `self._last_token_usage["cost_usd"]`.
This plan passes it through to the `token_usage.cost_usd` column — no backend calculation needed.
