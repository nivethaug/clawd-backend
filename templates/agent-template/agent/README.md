# Agent Guide - Scheduler Code Navigation & Modification

This folder helps AI assistants understand and modify the scheduler project efficiently.

---

## Architecture: Centralized Scheduler

**This project does NOT run its own scheduler loop, database, or PM2 process.** All job scheduling and execution is managed by the centralized backend (`services/scheduler/`). This project only contains:

1. **`scheduler/executor.py`** — Task handlers + dynamic content resolution (loaded by central execution engine)
2. **`scheduler/job_manager.py`** — HTTP client that calls the backend REST API to create/manage jobs
3. **`services/api_client.py`** — External API helper functions used by executor

The central backend handles: scheduler loop, job storage, schedule parsing, execution logging, and job lifecycle (pause/resume/delete).

---

## Your Two Jobs as an AI Agent

When the user asks for a new scheduled task (e.g., "send BTC price via email every 10 minutes"):

### Job 1: Add Task Logic (Code Changes)

Modify **two files** only:

**File A: `services/api_client.py`** — Add API helper function
```python
def get_crypto_price(coin_id: str = "bitcoin", currency: str = "usd") -> dict:
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": coin_id, "vs_currencies": currency}
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    # ... return {"success": True, "price": price}
```

**File B: `scheduler/executor.py`** — Add registry entry + task handler + route

```python
# 1. Add to FETCH_DATA_REGISTRY (for {{variable}} dynamic content)
FETCH_DATA_REGISTRY["btc_price"] = lambda: _fetch_crypto("bitcoin")

# 2. Add fetch helper function
def _fetch_crypto(coin: str) -> str:
    result = api_client.get_crypto_price(coin)
    if result.get("success"):
        return f"${result['price']:,.2f}"
    return "unavailable"

# 3. Add task handler
def _btc_email(payload: dict) -> Tuple[str, str]:
    price = _fetch_crypto("bitcoin")
    text = f"BTC Price: {price}"
    payload["body"] = text
    return _send_email(payload)

# 4. Add route in execute_task() function
elif task_type == 'btc_email':
    status, message = _btc_email(payload)
```

### Job 2: Create the Scheduled Job (API Call)

Use `job_manager` to register the job — this calls the backend REST API:

```python
from scheduler import job_manager

job_manager.create(
    job_type="interval",        # interval, daily, once
    schedule_value="10m",       # 30s, 5m, 1h, 2d, daily:09:00
    task_type="btc_email",      # MUST match your execute_task() route
    payload={
        "to": "user@email.com",
        "subject": "BTC Update",
        "body": "Bitcoin: {{btc_price}}",
        "fetch": ["btc_price"]  # Resolved before sending
    }
)
```

**CRITICAL**: `task_type` in `job_manager.create()` MUST exactly match the `elif task_type == '...'` route in `execute_task()`.

---

## Job Manager Tool Reference (`scheduler/job_manager.py`)

This is your primary tool for managing jobs. It wraps HTTP calls to the backend API.

```python
from scheduler import job_manager

# Create
job_manager.create(job_type, schedule_value, task_type, payload)

# Read
job_manager.list_jobs()           # All jobs for this project
job_manager.get(job_id)           # Single job details

# Update
job_manager.update(job_id, schedule_value="30m")  # Change schedule
job_manager.update(job_id, payload={"to": "new@email.com"})  # Change payload

# Control
job_manager.pause(job_id)         # Pause active job
job_manager.resume(job_id)        # Resume paused job
job_manager.run_now(job_id)       # Trigger immediately
job_manager.delete(job_id)        # Delete job

# Logs
job_manager.get_logs(job_id)      # Execution logs for one job
job_manager.get_project_logs()    # All execution logs
job_manager.clear_all()           # Delete all project jobs
```

---

## Dynamic Content System (`{{variable}}`)

Jobs can use `{{variable}}` placeholders that are resolved to live data at execution time.

### How It Works

```
Job payload:
{
  "fetch": ["btc_price"],
  "body": "Bitcoin: {{btc_price}}"
}

Execution:
1. executor.resolve_content(payload)
2. FETCH_DATA_REGISTRY["btc_price"]() → api_client.get_crypto_price("bitcoin")
3. "{{btc_price}}" replaced with "$94,231.00"
4. Email sent with live data
```

### FETCH_DATA_REGISTRY (in executor.py)

| Variable | Source | Example Value |
|----------|--------|---------------|
| `{{btc_price}}` | CoinGecko | `$94,231.00` |
| `{{eth_price}}` | CoinGecko | `$3,456.78` |
| `{{weather}}` | Open-Meteo | `15C, wind 10km/h` |
| `{{news}}` | Hacker News | `Story 1 \| Story 2 \| Story 3` |

Add new entries: `FETCH_DATA_REGISTRY["my_var"] = lambda: _fetch_my_data()`

---

## Schedule Types

| job_type | schedule_value | Example | Meaning |
|----------|---------------|---------|---------|
| `interval` | `"5m"`, `"1h"`, `"30s"`, `"2d"` | `"10m"` | Every N seconds/minutes/hours/days |
| `daily` | `"daily:HH:MM"` | `"daily:09:00"` | Every day at specific time |
| `once` | any string | `"now"` | Run once then mark completed |

---

## Existing Task Handlers

| task_type | Handler | What it does | Required Config |
|-----------|---------|--------------|-----------------|
| `telegram` | `_send_telegram()` | POST to Telegram Bot API | `TELEGRAM_BOT_TOKEN` in .env |
| `discord` | `_send_discord()` | POST to Discord webhook URL | `webhook_url` in payload |
| `email` | `_send_email()` | Send via SMTP | `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` in .env |
| `api` | `_call_api()` | HTTP request to any URL | `url` in payload |
| `trade` | `_execute_trade()` | Paper trade placeholder | None |

---

## Environment Variables (.env)

| Variable | Description | Required |
|----------|-------------|----------|
| `PROJECT_ID` | Project ID for job filtering | Auto-injected by worker |
| `PROJECT_PATH` | Filesystem path to project | Auto-injected by worker |
| `BACKEND_URL` | Backend API URL for job_manager | Auto-injected by worker |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Only for telegram tasks |
| `DISCORD_BOT_TOKEN` | Discord bot token | Only for discord tasks |
| `SMTP_HOST` | SMTP server | Only for email tasks |
| `SMTP_PORT` | SMTP port (default: 587) | Only for email tasks |
| `SMTP_USER` | SMTP username | Only for email tasks |
| `SMTP_PASS` | SMTP password | Only for email tasks |

**No DATABASE_URL** — jobs are stored in the main dreampilot DB, managed centrally.

---

## AI-Editable Files

### Primary Targets (SAFE TO MODIFY)

| File | What to modify | When |
|------|---------------|------|
| `scheduler/executor.py` | FETCH_DATA_REGISTRY + new task_type handlers + routes | Adding new task types or data variables |
| `services/api_client.py` | New API helper functions | Adding new data sources |

### Read-Only Files (DO NOT MODIFY)

| File | Reason |
|------|--------|
| `scheduler/job_manager.py` | Your tool — calls backend API, no business logic |
| `scheduler/__init__.py` | Package init |
| `config.py` | Environment config, no business logic |
| `main.py` | Thin entry point |
| `requirements.txt` | Dependencies |
| `llm/categories/` | API catalog (reference only) |

---

## How to Add New Features

### Add New Data Source (e.g., stock prices)

**Step 1:** Add API function in `services/api_client.py`
```python
def get_stock_price(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    response = requests.get(url, timeout=10)
    # ... parse response ...
    return {"success": True, "price": price}
```

**Step 2:** Add to `scheduler/executor.py`
```python
# Add to FETCH_DATA_REGISTRY
FETCH_DATA_REGISTRY["aapl_price"] = lambda: _fetch_stock("AAPL")

# Add helper
def _fetch_stock(symbol: str) -> str:
    result = api_client.get_stock_price(symbol)
    if result.get("success"):
        return f"${result['price']:,.2f}"
    return "unavailable"
```

**Step 3:** Create job using `job_manager`
```python
job_manager.create("interval", "1h", "email", {
    "to": "user@email.com",
    "subject": "AAPL Update",
    "body": "Apple: {{aapl_price}}",
    "fetch": ["aapl_price"]
})
```

### Add New Task Type (e.g., slack notification)

**Step 1:** Add handler in `scheduler/executor.py`
```python
def _send_slack(payload: dict) -> Tuple[str, str]:
    webhook_url = payload.get('webhook_url')
    text = payload.get('text', '')
    response = requests.post(webhook_url, json={"text": text}, timeout=10)
    response.raise_for_status()
    return ('success', 'Slack message sent')
```

**Step 2:** Add route in `execute_task()` function
```python
elif task_type == 'slack':
    status, message = _send_slack(payload)
```

**Step 3:** Create job
```python
job_manager.create("interval", "30m", "slack", {
    "webhook_url": "https://hooks.slack.com/...",
    "text": "Status update: {{news}}",
    "fetch": ["news"]
})
```

---

## API Selection Reference

The `llm/categories/` directory contains a catalog of public APIs organized by category:

| Category | APIs | Use Case |
|----------|------|----------|
| `crypto_finance` | CoinGecko | Crypto prices, market data |
| `weather` | Open-Meteo | Temperature, forecasts |
| `news` | Hacker News | Top stories |
| `entertainment` | JokeAPI, trivia | Fun content |
| `stocks` | Alpha Vantage | Stock prices |
| `location` | IP geolocation | Location data |
| `utilities` | Math, random, QR | Utility functions |
| `currency` | Exchange rates | Currency conversion |
| `sports` | Sports scores | Match updates |
| `health` | Health data | Fitness tracking |
| `ai` | AI APIs | Text generation |
| `science` | Science data | Research info |
| `food` | Recipe APIs | Recipe data |
| `travel` | Travel APIs | Flight/hotel info |
| `jobs` | Job APIs | Job listings |
| `knowledge` | Wikipedia | Reference data |
| `security` | Security APIs | Threat info |
| `ecommerce` | Product APIs | Shopping data |
| `images` | Image APIs | Photo data |

Check `llm/categories/index.json` for the full catalog with endpoints and parameters.

---

## Web Scraping Extension (LLM How-To)

Use `services/web_scraper.py` when the target site requires browser rendering or user-like interaction.

### Where to Extend

1. Add scraping helper wrapper in `services/api_client.py`.
2. Optionally create custom class in `services/web_scraper.py` by subclassing `WebScraper`.
3. Register custom scraper using `register_scraper("name", MyScraper)`.
4. Use returned data in `scheduler/executor.py` (new `FETCH_DATA_REGISTRY` key or task handler).

### Minimal Pattern

```python
from services.web_scraper import ScrapeConfig, scrape_url

def scrape_market_headlines(url: str) -> dict:
    config = ScrapeConfig(
        url=url,
        items_selector="article",
        fields={"title": "h2, h3", "link": "a"},
        max_pages=1,
        scroll=True
    )
    result = scrape_url(url, config)
    return {
        "success": len(result.errors) == 0,
        "items": result.data,
        "errors": result.errors
    }
```

### Integration Example in Scheduler

```python
# scheduler/executor.py
FETCH_DATA_REGISTRY["market_news"] = lambda: _fetch_market_news()

def _fetch_market_news() -> str:
    result = api_client.scrape_market_headlines("https://example.com")
    if result.get("success") and result.get("items"):
        return " | ".join(item.get("title", "") for item in result["items"][:3])
    return "unavailable"
```

Rules:
- Keep scheduler routing in `scheduler/executor.py`; keep scraping internals in `services/`.
- Use precise selectors and bounded pagination.
- Update `agent/ai_index/*.json` after adding new scraper helpers.

---

## File Structure

```
scheduler-template/
├── main.py              # Thin entry point (no server, no endpoints)
├── config.py            # Environment config (PROJECT_ID, BACKEND_URL, task tokens)
├── requirements.txt     # Dependencies (requests, python-dotenv)
├── .env.example         # Environment template
├── .gitignore
├── scheduler/
│   ├── __init__.py      # Package init
│   ├── executor.py      # Task routing + FETCH_DATA_REGISTRY + handlers (YOU MODIFY)
│   └── job_manager.py   # HTTP client for job CRUD (YOUR TOOL)
├── services/
│   ├── __init__.py
│   └── api_client.py    # External API helpers (YOU MODIFY)
├── llm/
│   └── categories/      # Public API catalog (17 categories, reference only)
│       ├── index.json    # Master index
│       ├── crypto_finance.json
│       ├── weather.json
│       └── ...
└── agent/
    ├── README.md        # This file
    └── ai_index/        # Code navigation index (JSON)
        ├── files.json
        ├── symbols.json
        ├── summaries.json
        ├── modules.json
        └── dependencies.json
```

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Unknown task_type: X` | No route for task_type in `execute_task()` | Add `elif task_type == 'X':` route |
| `SMTP not configured` | Missing SMTP_* vars in .env | Set SMTP_HOST, SMTP_USER, SMTP_PASS |
| `TELEGRAM_BOT_TOKEN not configured` | Missing token in .env | Set TELEGRAM_BOT_TOKEN |
| `Unknown fetch key: X` | Not in FETCH_DATA_REGISTRY | Add entry to registry in executor.py |
| Job created but never runs | task_type mismatch | Ensure create() task_type matches execute_task() route |
| `BACKEND_URL` unreachable | Wrong URL or backend down | Check .env BACKEND_URL, verify backend running |

---

## Best Practices

1. **Keep executor.py clean** — Only FETCH_DATA_REGISTRY + handlers + routing
2. **Use api_client.py for APIs** — All external calls go there
3. **Use {{variable}} + fetch** — Dynamic content via FETCH_DATA_REGISTRY
4. **Match task_type** — create() task_type MUST equal execute_task() elif route
5. **Never crash** — All handlers wrapped in try/except, return ('failed', message)
6. **Use job_manager** — Never access DB directly, always via job_manager API
7. **Check llm/categories/** — Reference API catalog before adding new integrations

---

## License

MIT
