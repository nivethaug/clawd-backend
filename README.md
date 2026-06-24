# Clawd Backend — Project Create & Clone

## Project Folder Structure

All projects live under `/root/dreampilot/projects/{type}/`:

```
/root/dreampilot/projects/
├── website/          ← type_id=1 (websites)
│   └── {id}_{slug}_{timestamp}/
│       ├── frontend/
│       ├── backend/
│       └── .env
├── telegram/         ← type_id=2 (Telegram bots)
│   └── {id}_{slug}_{timestamp}/
│       ├── telegram/
│       │   ├── main.py
│       │   ├── .env          ← bot reads THIS file
│       │   ├── .env.example  ← clean template
│       │   └── logs/
│       └── project.json
├── discord/          ← type_id=3 (Discord bots)
│   └── {id}_{slug}_{timestamp}/
│       └── discord/
│           ├── main.py
│           └── .env
├── trading/          ← type_id=4 (Trading bots)
└── scheduler/        ← type_id=5 (Schedulers)
```

**Folder naming convention:** `{project_id}_{slugified_name}_{YYYYMMDD_HHMMSS}`

Example: `1604_crytpo-copy_20260624_040412`

## OpenClaw Project Folder Path

OpenClaw task runner (`openclaw_tasks.py`) receives the project path as an argument:

```bash
python3 openclaw_tasks.py <project_id> <project_path> <project_name>
```

The `project_path` is the full absolute path returned by `ProjectFileManager.build_type_based_path()`:

```
/root/dreampilot/projects/{type_folder}/{id}_{slug}_{timestamp}
```

Example for a Telegram bot:
```
/root/dreampilot/projects/telegram/1604_crytpo-copy_20260624_040412
```

For the bot subdirectory specifically (where `main.py` lives):
```
/root/dreampilot/projects/telegram/{id}_{slug}_{timestamp}/telegram/
```

## Clone Flow (`POST /projects/{id}/clone`)

### Endpoint
`POST /projects/{project_id}/clone`

### Request Body
```json
{
  "name": "My Clone Bot",
  "domain": "optional-custom-domain",
  "bot_token": "new-bot-token",
  "telegram_bot_token": "alternative-token-key",
  "telegram_chat_id": "optional",
  "discord_webhook_url": "optional",
  "email_to": "optional"
}
```

### Pipeline Steps (Background Worker `_clone_worker`)

```
1. Copy files        source_path → clone_path (shutil.copytree)
2. Git re-init       Remove source .git, fresh init + commit
3. GitHub repo       Create new repo, add remote
4. Domain replace    Replace source domain in config files
5. project.json      Write clone metadata
6. .env injection    Type-specific:
                     ├─ Telegram: inject_bot_token() regenerates clean .env from .env.example
                     │            with clone's BOT_TOKEN, WEBHOOK_DOMAIN, WEBHOOK_URL, PORT,
                     │            PROJECT_ID, DATABASE_URL
                     └─ Discord: _update_env_file() patches keys in existing .env
7. Start PM2         start_bot_pm2() — deletes old process, writes merged .env, starts fresh
8. Nginx             Generate + install config for clone domain, reload
9. DNS               Create A record: {clone_domain}.dreambigwithai.com → server IP
10. Webhook          register_webhook_async() — background thread, 9 retries, exponential backoff
11. Final            Set project status = "ready"
```

### Clone Environment Propagation (Telegram)

The `.env` is written in three stages to ensure no stale source values survive:

| Stage | Function | What happens |
|-------|----------|-------------|
| After copy | (source files) | `.env` has source project's stale values (old token, domain, port, project_id) |
| After `inject_bot_token()` | `env_injector.py` | Regenerates from `.env.example` template with clone values. Reads `DATABASE_URL` from source `.env` before overwriting. |
| After `start_bot_pm2()` | `pm2_manager.py` | Reads the clean `.env`, merges with explicit params, writes back. Sets both `BOT_TOKEN` and `TELEGRAM_BOT_TOKEN`. |

**Key fix:** `DATABASE_URL` is extracted from the source `.env` *before* `inject_bot_token` runs and passed through, otherwise it would be reset to the `.env.example` placeholder.

### PM2 Process Naming

- **Telegram:** `{domain}-bot` if domain provided, else `tg-bot-{project_id}`
- **Discord:** `dc-bot-{project_id}` (always)

### Debugging

Clone debug logs use `[CLONE-DEBUG]` prefix (single-line for grep visibility):

```bash
pm2 logs clawd-backend --lines 200 | grep CLONE-DEBUG
```

Shows `.env` content at each stage (tokens masked):
- After copy (source values)
- After `inject_bot_token` (should be clean)
- After `start_bot_pm2` (final state PM2 reads)

---

## Create Flow (`POST /projects`)

### Phase 1: Input Validation & Request parsing

**Validation steps:**
1. **Subdomain validation** (`validate_subdomain()`)
   - Length check (3-50 chars)
   - Lowercase letters, numbers, hyphens only
   - Must start with a letter