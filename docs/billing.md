# Billing and AI Credits

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

Billing tracks plans, AI credits, edit tokens, credit packs, LemonSqueezy checkout/webhooks, and admin billing controls.

## Main Files

| File | Responsibility |
| --- | --- |
| `api/billing_router.py` | `/api/billing/*` routes |
| `services/billing_service.py` | Credit accounting and cascade charging |
| `services/plan_cache.py` | Cached plans, grants, operations, config |
| `services/billing_cron.py` | Monthly reset daemon |
| `services/lemonsqueezy_service.py` | Checkout and webhook processing |
| `api/lemonsqueezy_webhook.py` | `/webhooks/lemonsqueezy` |

## Credit Model

Credit balances are generic by `credit_type`.

Current credit types:

- `project_ai`
- `edit_token`

Edit operations use this cascade:

```text
edit_token monthly -> project_ai monthly -> project_ai purchased
```

Creation operations use:

```text
project_ai monthly -> project_ai purchased
```

All deductions write `credit_transactions` rows for auditability.

## Core Tables

| Table | Purpose |
| --- | --- |
| `billing_plans` | Plan catalog |
| `plan_credit_grants` | Monthly credits per plan/type |
| `user_credit_balances` | User balances by credit type |
| `ai_operations` | Operation costs and categories |
| `credit_transactions` | Audit log for charges/refunds/purchases |
| `credit_packs` | Purchasable credit packs |
| `subscriptions` | Subscription state |
| `billing_config` | JSONB config key/value store |

## User Routes

Prefix: `/api/billing`

| Method | Endpoint | Auth | Description |
| --- | --- | --- | --- |
| GET | `/plans` | public | Active plans for pricing |
| GET | `/summary` | user | Plan, balances, and transactions |
| GET | `/balances` | user | Credit balances |
| GET | `/transactions` | user | Paginated transaction history |
| GET | `/credit-packs` | public | Purchasable credit packs |
| POST | `/checkout/plan/{plan_slug}` | user | LemonSqueezy plan checkout |
| POST | `/checkout/credits` | user | LemonSqueezy credit checkout |

## Admin Routes

Prefix: `/api/billing`

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/admin/users` | Billing user list |
| GET | `/admin/users/{user_id}` | User billing detail |
| POST | `/admin/assign-plan` | Assign plan and sync balances |
| POST | `/admin/add-credits` | Grant purchased credits |
| GET | `/admin/operations` | Operation costs |
| PUT | `/admin/operations/{op_code}` | Update operation cost/config |
| GET | `/admin/config` | Billing config |
| PUT | `/admin/config` | Update billing config |
| POST | `/admin/reset-monthly` | Trigger monthly reset |
| GET | `/admin/stats` | Aggregate billing stats |

## Checkout Requests

Plan checkout:

```json
POST /api/billing/checkout/plan/pro
```

Credit checkout:

```json
{
  "pack_id": 1
}
```

Both return a LemonSqueezy checkout URL when payment configuration is available.

## Webhook

`POST /webhooks/lemonsqueezy`

Processes subscription events and credit pack orders. Signature verification is handled by `services/lemonsqueezy_service.py`; dev mode may skip signature checks when no webhook secret is configured.

## Integration Points

| Flow | Billing behavior |
| --- | --- |
| Project creation | Checks plan/project limits and charges creation operation |
| Streaming chat edit | Reserves `ADD_FEATURE`, reconciles token usage, refunds on failure |
| Non-streaming chat edit | Charges token usage after completion |
| Monthly reset | `billing_cron.py` calls `reset_monthly_credits()` idempotently |

## Related

- [TOKEN_USAGE_TRACKING.md](./TOKEN_USAGE_TRACKING.md)
- [ADMIN_USER_MANAGEMENT.md](./ADMIN_USER_MANAGEMENT.md)
- [backend_api_reference.md](./backend_api_reference.md)
