# Admin User Management

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

Admin user management lets admins view users, update roles/tiers, reset rate limits, and inspect token usage.

## Main Endpoints

All endpoints require an admin user.

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/admin/users` | Paginated users with token/cost totals |
| PUT | `/admin/users/{target_user_id}` | Update role and/or subscription tier |
| POST | `/admin/users/{target_user_id}/reset-limits` | Reset rate-limit counters |
| GET | `/admin/stats` | Platform stats |
| GET | `/admin/tiers` | Tier configuration |
| PUT | `/admin/tiers/{tier_name}` | Update tier configuration |
| GET | `/admin/users/{target_user_id}/limits` | User limit details |
| PUT | `/admin/users/{target_user_id}/limits` | Override user limits |
| GET | `/admin/usage` | Platform token usage |
| GET | `/admin/usage/logs` | Raw usage logs with filters |

## GET `/admin/users`

Query params:

| Param | Default | Description |
| --- | --- | --- |
| `limit` | `50` | Page size |
| `offset` | `0` | Pagination offset |
| `sort` | `cost` | `cost` or `id` |

Response:

```json
{
  "users": [
    {
      "id": 1,
      "email": "admin@example.com",
      "name": "Admin",
      "role": "admin",
      "subscription_tier": "pro",
      "created_at": "2026-07-12 10:00:00",
      "total_tokens": 12345,
      "total_cost_usd": 0.42
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

## PUT `/admin/users/{target_user_id}`

Request:

```json
{
  "role": "admin",
  "subscription_tier": "pro"
}
```

Only configured roles/tiers are accepted.

## Usage Inspection

Use `/admin/usage/logs` with optional filters:

| Param | Description |
| --- | --- |
| `user_id` | Filter by user |
| `project_id` | Filter by project |
| `usage_type` | `ai_chat`, `project_create`, or `ai_completion` |
| `limit` | Max 200 |
| `offset` | Pagination offset |

## Related

- [TOKEN_USAGE_TRACKING.md](./TOKEN_USAGE_TRACKING.md)
- [billing.md](./billing.md)
