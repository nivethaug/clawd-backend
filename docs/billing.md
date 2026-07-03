# Billing & Subscription System Documentation

> **Last Updated:** 2026-07-03  
> **Purpose:** Complete reference for the AI Credits billing architecture, database schema, service layer, API endpoints, frontend components, and monthly reset cron.

---

## Overview

The billing system uses an **AI Credits architecture** designed for scalability to 100,000+ users. It is **100% database-driven** with **no hardcoded plans, credit values, or limits**.

### Core Design Principles

- **Generic Credit Model**: One row per `(user_id, credit_type)` in `user_credit_balances`
- **Credit Types**: `project_ai`, `edit_token` (future: `image`, `video`, `voice`, `api`, `marketplace`)
- **Cascade Logic** (unconditional — not gated by `EARLY_ACCESS_MODE`):
  - Edit operations (category=`edit`): `edit_token(monthly)` → `project_ai(monthly)` → `project_ai(purchased)`
  - Creation operations (category=`creation`): `project_ai(monthly)` → `project_ai(purchased)`
- **Two-Phase Billing** for AI edits: temporary hold → reconciliation → refund excess
- **Cache-Read Exclusion**: `cache_read_input_tokens` excluded from billing (cheap re-reads, not new processing)
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
- **`status` values**: `reserved` (temporary hold), `charged` (final deduction), `refunded` (reversed)

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
- `_cascade_order()`:114 — edit ops always try `edit_token` first (unconditional)
- `can_afford()`:140 — returns cascade breakdown, sums across all tiers
- `_charge_tier()`:190 — deducts from a single tier, returns amount actually deducted
- `reserve_credits()`:251 — temporary hold, records `status="reserved"`
- `refund_credits()`:331 — reverses cascade, records `status="refunded"` audit rows
- `charge_token_usage()`:370 — **reconciliation**: charges net = max(0, billable − precharged)
- `charge_project_creation()`:485 — looks up operation by `project_type_id`
- `add_purchased_credits()`:506
- `sync_balances_to_plan()`:526
- `assign_plan()`:557
- `get_user_billing_summary()`:578
- `reset_monthly_credits()`:626 — used by cron + admin

**Critical Schema Alignment**:
- Uses `credit_cost` (not `cost_credits`)
- Transaction uses `operation_id`, `credits`, `status` (not `operation_code`/`delta`/`balance_after`)

**Two-Phase Billing Flow** (for AI edits):

1. **Pre-charge** (`reserve_credits`): Deducts flat `credit_cost` (e.g., 2 for `ADD_FEATURE`) as a `status="reserved"` temporary hold. Returns `charged[]` list.
2. **Post-charge** (`charge_token_usage`): After edit completes, deducts actual tokens (minus cache reads). Passes `precharged_amount` so it doesn't double-charge. Net = `max(0, billable_tokens − precharged_amount)`.
3. **Refund** (`refund_credits`): If edit fails or produces 0 tokens, reverses the hold with `status="refunded"`.

**Cache-Read Exclusion**: `charge_token_usage()` accepts `cache_read_tokens` param. Billable = `max(0, total_tokens − cache_read_tokens)`. Typically reduces charges by ~70%.

**Cascade Guarantee**: `_cascade_order()` for edit operations (category=`edit`) always returns `[edit_token(monthly), project_ai(monthly), project_ai(purchased)]` regardless of `EARLY_ACCESS_MODE`. Creation ops use `[project_ai(monthly), project_ai(purchased)]`.

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
| `/transactions` | GET | Paginated history with `description` field | 120 |
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
  - Registered in `app.py` via `app.include_router(lemonsqueezy_webhook_router, prefix="/webhooks")`
  - `order_created` → `add_purchased_credits()` — triple fallback for variant ID lookup (`first_order_item.variant_id` → `attrs.variant_id` → `custom_data.pack_id`)

---

## Integration Points in `app.py`

**Project Creation** (`app.py:605-635`):
- After project limit check + type resolution, calls `charge_project_creation()`
- Operation code mapped from `project_type_id` (e.g., Website→`WEBSITE`, Telegram→`TELEGRAM_BOT`)
- Credits read from `ai_operations` table — no hardcoded costs
- On folder creation failure: `refund_credits(..., "WEBSITE", charged)`

**Chat Streaming** (`app.py:4769-5220`):
- **Pre-charge**: `reserve_credits(..., "ADD_FEATURE")` → `status="reserved"` hold (2 credits)
- **Post-charge**: `charge_token_usage()` with `precharged_amount` + `cache_read_tokens` — reconciles hold against actual usage
- **Error refund**: `refund_credits(...)` on exceptions
- **0-token refund**: if edit completes with 0 billable tokens, hold is refunded

**Chat Non-Streaming** (`app.py:5610-5635`):
- No pre-charge; `charge_token_usage()` with `precharged_amount=0` charges full actual usage post-edit

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

- `EARLY_ACCESS_MODE`: boolean — historical; cascade is now unconditional for edits. Still gates some legacy features.
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
