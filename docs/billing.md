# Billing & Subscription System Documentation

> **Last Updated:** 2026-06-28  
> **Purpose:** Complete reference for the AI Credits billing architecture, database schema, service layer, API endpoints, frontend components, and monthly reset cron.

---

## Overview

The billing system uses an **AI Credits architecture** designed for scalability to 100,000+ users. It is **100% database-driven** with **no hardcoded plans, credit values, or limits**.

### Core Design Principles

- **Generic Credit Model**: One row per `(user_id, credit_type)` in `user_credit_balances`
- **Credit Types**: `project_ai`, `edit_token` (future: `image`, `video`, `voice`, `api`, `marketplace`)
- **Cascade Logic** (when `EARLY_ACCESS_MODE=true`):
  - Edit operations: `edit_token(monthly)` → `project_ai(monthly)` → `project_ai(purchased)`
  - Creation operations: `project_ai(monthly)` → `project_ai(purchased)`
- **Never blocks** while any balance remains
- **LemonSqueezy** integration for plans and credit packs with graceful fallback
- **Monthly auto-reset** via dedicated daemon thread (`billing_cron.py`)

---

## Database Schema

All tables are defined in `database_postgres.py:948-~1150` with migrations, seeds, and backfills.

### Core Tables

**`plans`** (`database_postgres.py:960`)
- `id`, `slug`, `name`, `price_monthly_cents`, `max_active_projects`, `features` (JSONB), `lemonsqueezy_variant_id`

**`plan_credit_grants`** (`database_postgres.py:975`)
- Junction table: `plan_id`, `credit_type`, `monthly_limit`

**`user_credit_balances`** (`database_postgres.py:985`)
- `user_id`, `credit_type`, `monthly_limit`, `used`, `purchased`, `reset_date`
- **Note**: No `plan_id` column (balances are synced via `sync_balances_to_plan`)

**`ai_operations`** (`database_postgres.py:1000`)
- `code`, `name`, `credit_cost`, `category`, `credit_type`, `enabled`

**`credit_transactions`** (`database_postgres.py:1015`)
- `id`, `user_id`, `operation_id`, `credit_type`, `credits`, `status`, `cost_usd`, `model`, `input_tokens`, `output_tokens`, `total_tokens`, `duration_ms`, `provider`, `project_id`, `session_id`

**`credit_packs`**, **`subscriptions`**, **`billing_config`** (JSONB key/value store)

**Seeds** (executed on first run):
- 4 plans (free/pro/dream/enterprise)
- 8 plan grants
- 13 AI operations
- 3 credit packs
- `EARLY_ACCESS_MODE=true`

### Migration Helper

All changes use `_run_migration()` pattern in `database_postgres.py`.

---

## Service Layer

### 1. `services/plan_cache.py:22` — `_PlanCache` Singleton

- Thread-safe with `RLock`
- 60s TTL with auto-refresh
- Key functions:
  - `get_plan()`, `get_all_plans()`
  - `get_plan_grants(plan_id)`
  - `get_operation(code)`, `get_operation_for_type(type_id)`
  - `is_early_access_enabled()` — checks env then `billing_config`
  - `get_billing_config(key)`, `invalidate(scope)`

### 2. `services/billing_service.py:35` — Core Accounting

**Key Functions** (line ranges):

- `get_or_create_balance()`:35
- `can_afford()`:140 — returns cascade breakdown
- `reserve_credits()`:251 — pre-check + charge
- `refund_credits()`:326 — reverses cascade
- `charge_project_creation()`:353 — looks up operation by `project_type_id`
- `add_purchased_credits()`:374
- `sync_balances_to_plan()`:394
- `assign_plan()`:425
- `get_user_billing_summary()`:446
- `reset_monthly_credits()`:494 — used by cron + admin

**Critical Schema Alignment**:
- Uses `credit_cost` (not `cost_credits`)
- Transaction uses `operation_id`, `credits`, `status` (not `operation_code`/`delta`/`balance_after`)

### 3. `services/billing_cron.py:142` — Monthly Reset Daemon

- Runs as daemon thread started in `app.py:485`
- Checks hourly (`BILLING_CRON_INTERVAL`)
- Configurable reset day via `billing_config.MONTHLY_RESET_DAY`
- Idempotent using `MONTHLY_RESET_LAST_RUN`
- Calls `reset_monthly_credits()` and records system transaction

### 4. Other Services

- `services/rate_limiter.py:85` — uses `_get_tier_config()` from plan_cache
- `services/token_tracker.py:120` — extended with billing metadata
- `services/lemonsqueezy_service.py:31` — checkout, webhook processing, portal URLs

---

## API Endpoints (`api/billing_router.py`)

**Public (no auth required for plans)**

| Endpoint | Method | Purpose | Lines |
|----------|--------|---------|-------|
| `/plans` | GET | List all plans | 65 |
| `/credit-packs` | GET | List purchasable packs | 142 |

**Authenticated User**

| Endpoint | Method | Purpose | Lines |
|----------|--------|---------|-------|
| `/summary` | GET | Full billing summary (plan + balances + recent tx) | 87 |
| `/balances` | GET | Current credit balances | 96 |
| `/transactions` | GET | Paginated transaction history | 119 |
| `/checkout/plan/{slug}` | POST | LemonSqueezy checkout for plan | 157 |
| `/checkout/credits` | POST | LemonSqueezy checkout for credit pack | 196 |

**Admin Only**

| Endpoint | Method | Purpose | Lines |
|----------|--------|---------|-------|
| `/admin/users` | GET | List users with plan info | 242 |
| `/admin/users/{id}` | GET | Full user billing summary | 267 |
| `/admin/assign-plan` | POST | Assign plan + sync balances | 278 |
| `/admin/add-credits` | POST | Grant purchased credits | 298 |
| `/admin/operations` | GET | View/edit credit costs | 311 |
| `/admin/operations/{code}` | PUT | Update operation cost/enabled | 322 |
| `/admin/config` | GET/PUT | View/update `billing_config` | 356, 368 |
| `/admin/reset-monthly` | POST | Manual monthly reset | 392 |
| `/admin/stats` | GET | Aggregate billing stats | 405 |

**Webhook**

- `POST /webhooks/lemonsqueezy` (`api/lemonsqueezy_webhook.py:22`) — processes subscription & order events

---

## Integration Points in `app.py`

**Project Creation** (`app.py:549-575`):
- After project limit check, calls `charge_project_creation()`
- On failure: `refund_credits(..., "project_create", charged)`

**Chat Streaming** (`app.py:4767-5180`):
- `reserve_credits(..., "ADD_FEATURE")` before ACP streaming
- `refund_credits(...)` on errors
- Enhanced `token_tracker.record_usage()` with `credits_charged`

**Startup** (`app.py:483-488`):
- Starts `billing_cron.start_billing_cron()` (idempotent)

---

## Frontend (`muse-companion-app/`)

**Components**:

- `src/components/CreditIndicator.tsx` — Live badge in header with tooltip (refreshes every 30s)
- `src/components/ClawdbotHeader.tsx:25` — Includes `<CreditIndicator />`

**Pages**:

- `src/pages/Billing.tsx` — Plans, credit packs, balances with progress bars, transaction history
- `src/pages/AdminBilling.tsx` — Admin dashboard with user management, operation editing, config toggles, stats

**API Client** (`src/lib/api.ts:1315`):
- `billingApi` and `adminBillingApi` namespaces with full TypeScript interfaces

**Routes** (`src/App.tsx:170`):
- `/app/billing` (protected)
- `/app/admin/billing` (admin only)

---

## LemonSqueezy Integration (`services/lemonsqueezy_service.py:142`)

- `process_webhook_event()` handles:
  - `subscription_created` / `subscription_updated` / `subscription_cancelled`
  - `order_created` for credit packs
- Uses `lemonsqueezy_variant_id` to map to plans/packs
- Calls `assign_plan()` or `add_purchased_credits()`

**Webhook Verification**: HMAC-SHA256. Dev mode skips signature if no secret.

---

## Configuration (`billing_config` table)

Stored as JSONB. Key values:

- `EARLY_ACCESS_MODE`: boolean — enables cascade to project_ai credits for edits
- `MONTHLY_RESET_DAY`: int (default: 1)
- `MONTHLY_RESET_LAST_RUN`: ISO date (managed by cron)

Use admin endpoints or direct DB to modify.

---

## Testing & Verification

All files pass `py_compile`. Frontend has zero TypeScript errors.

**Manual Verification Commands**:

```bash
# Backend syntax
cd clawd-backend
python -c "
import py_compile
for f in ['database_postgres.py','services/plan_cache.py','services/billing_service.py','services/billing_cron.py','api/billing_router.py','app.py']:
    py_compile.compile(f, doraise=True)
print('All billing files compile clean')
"

# Frontend type check
cd ../muse-companion-app
npx tsc --noEmit
```

**API Test Examples**:

```bash
# Get plans (public)
curl http://localhost:8000/api/billing/plans

# User summary
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/api/billing/summary

# Admin reset
curl -X POST -H "Authorization: Bearer ADMIN_TOKEN" http://localhost:8000/api/billing/admin/reset-monthly
```

---

## Related Files

- `IMPLEMENTATION_SUMMARY.md` — Overall feature summary
- `POSTGRESQL_MIGRATION_GUIDE.md` — DB migration steps
- `ai_chat.md` — AI chat system (uses billing for `ADD_FEATURE` operations)
- `database_postgres.py:948` — Full schema + seeds
- `services/billing_service.py:140` — Core cascade logic (`can_afford`)

**For AI Agents**: Start with this document, then drill into `billing_service.py` for business logic and `billing_router.py` for endpoints.

---
