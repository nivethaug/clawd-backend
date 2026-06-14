# Admin User Management Page — Implementation Plan

## Overview

New page at `/app/admin/users` for admins to manage users **and** view per-user token usage with project-wise filtering.

---

## Backend Status: ✅ All endpoints exist

| Endpoint | Purpose |
|----------|---------|
| `GET /admin/users` | List users (paginated) |
| `PUT /admin/users/{id}` | Update role / tier |
| `POST /admin/users/{id}/reset-limits` | Reset rate limits |
| `GET /admin/stats` | Platform-wide stats |
| `GET /admin/usage?period=` | Platform token totals + top users |
| `GET /admin/usage/logs?user_id=&project_id=&usage_type=` | Raw usage logs (filterable) |
| `GET /auth/usage?period=&usage_type=` | Current user's usage summary |
| `GET /projects/{id}/usage?period=` | Per-project token usage |

**No backend changes needed.**

---

## Frontend Tasks

### Task 1: Extend auth store with role

**File:** `src/lib/auth.ts`

```typescript
interface User {
  id: string;
  email: string;
  name?: string;
  role?: string;              // ← ADD
  subscription_tier?: string; // ← ADD
}
```

Add convenience getter:
```typescript
isAdmin: () => boolean,  // returns user?.role === 'admin'
```

---

### Task 2: Add API functions

**File:** `src/lib/api.ts`

```typescript
// ── Admin user management ──
export const adminApi = {
  getUsers: async (limit = 50, offset = 0) => {
    const res = await api.get('/admin/users', { params: { limit, offset } });
    return res.data; // { users: [...], total, limit, offset }
  },

  updateUser: async (userId: number, data: { role?: string; subscription_tier?: string }) => {
    const res = await api.put(`/admin/users/${userId}`, data);
    return res.data; // { success, user }
  },

  resetLimits: async (userId: number) => {
    const res = await api.post(`/admin/users/${userId}/reset-limits`);
    return res.data; // { success, message }
  },

  getStats: async () => {
    const res = await api.get('/admin/stats');
    return res.data;
  },
};

// ── Token usage ──
export interface TokenUsageSummary {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  count: number;
  by_type?: Record<string, { total_tokens: number; count: number }>;
  daily?: Array<{ date: string; total_tokens: number; count: number }>;
}

export interface TokenUsageLog {
  id: number;
  user_id: number;
  project_id: number | null;
  session_id: number | null;
  usage_type: string;
  description: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  model: string | null;
  created_at: string;
}

export const usageApi = {
  // Admin: platform-wide usage
  getPlatformUsage: async (period = 'month') => {
    const res = await api.get('/admin/usage', { params: { period } });
    return res.data;
  },

  // Admin: filtered usage logs (user + project filter)
  getUsageLogs: async (params: {
    user_id?: number;
    project_id?: number;
    usage_type?: string;
    limit?: number;
    offset?: number;
  }) => {
    const res = await api.get('/admin/usage/logs', { params });
    return res.data; // { logs: TokenUsageLog[], total, limit, offset }
  },

  // Per-project usage (works for admin viewing any project)
  getProjectUsage: async (projectId: number, period = 'all') => {
    const res = await api.get(`/projects/${projectId}/usage`, { params: { period } });
    return res.data;
  },
};
```

---

### Task 3: AdminGuard component

**File:** `src/components/AdminGuard.tsx` (new)

- Checks `useAuth().user?.role === 'admin'`
- If not admin → `<Navigate to="/app" />` + toast
- Pattern mirrors `AuthGuard`

---

### Task 4: Admin Users Page

**File:** `src/pages/AdminUsers.tsx` (new)

#### Layout structure:

```
ClawdbotLayout
├── Stats Banner (GET /admin/stats)
│   ├── Total Users | Total Projects | Total Sessions
│   ├── Users by Tier (free/pro/dream badges)
│   └── Users by Role (user/admin badges)
│
├── Platform Token Usage Banner (GET /admin/usage)
│   ├── Total tokens this month
│   ├── Breakdown by type (ai_chat / project_create / ai_completion)
│   └── Top 5 token consumers
│
├── Search Bar (filter by email/name)
│
├── Users Table (ui/table.tsx)
│   Columns: Name | Email | Role (badge) | Tier (badge) | Created | Actions
│   Row click → opens UserDetailDrawer
│   Actions: Edit (role/tier dialog), Reset Limits, View Usage
│
└── Pagination (ui/pagination.tsx)
```

#### Data fetching:
- `useQuery(['admin-users', page, search])` → `adminApi.getUsers()`
- `useQuery(['admin-stats'])` → `adminApi.getStats()`
- `useQuery(['platform-usage', period])` → `usageApi.getPlatformUsage()`
- `useMutation` for `updateUser` / `resetLimits` → invalidate `['admin-users']`

---

### Task 5: User Token Usage Drawer (the key feature)

**File:** `src/components/UserUsageDrawer.tsx` (new)

Opens when admin clicks "View Usage" on a user row.

#### Features:

1. **User header** — name, email, role, tier

2. **Period selector** — `Select` dropdown: Today / Week / Month / All Time

3. **Summary cards** — fetched from filtered logs:
   - Total tokens consumed
   - Input tokens
   - Output tokens
   - Total API calls

4. **Project filter dropdown** — `Select` populated from the user's projects:
   - "All Projects" (default)
   - Each project listed by name
   - When selected, filters the usage logs + summary by that project
   - Fetches user's projects via `projectsApi` filtered by user (or from `/admin/usage/logs` grouping)

5. **Usage type filter** — `ToggleGroup`: All | AI Chat | Project Create | AI Completion

6. **Usage breakdown chart** — simple bar chart (or list) showing tokens by type

7. **Recent usage logs table** (filtered by user + project + type):
   - Columns: Time | Project | Type | Description | Model | Input | Output | Total
   - Uses `GET /admin/usage/logs?user_id=X&project_id=Y&usage_type=Z`
   - Paginated (50 per page)

#### Data flow:
```typescript
// User's projects for the filter dropdown
const { data: userProjects } = useQuery({
  queryKey: ['admin-user-projects', userId],
  queryFn: () => api.get(`/admin/usage/logs`, { params: { user_id: userId, limit: 200 } })
    .then(res => {
      // Extract unique project_ids from logs
      const uniqueProjects = [...new Set(res.data.logs.map(l => l.project_id).filter(Boolean))];
      return uniqueProjects;
    }),
});

// Filtered logs
const { data: usageLogs } = useQuery({
  queryKey: ['user-usage-logs', userId, selectedProject, selectedType, period, page],
  queryFn: () => usageApi.getUsageLogs({
    user_id: userId,
    project_id: selectedProject || undefined,
    usage_type: selectedType || undefined,
    limit: 50,
    offset: page * 50,
  }),
});
```

---

### Task 6: Route + Navigation

**File:** `src/App.tsx`

```tsx
import AdminUsersPage from "./pages/AdminUsers";

<Route
  path="/app/admin/users"
  element={
    <AuthGuard>
      <AdminUsersPage />
    </AuthGuard>
  }
/>
```

**File:** `src/pages/Settings.tsx` or `src/components/BottomNavbar.tsx`

Add conditional admin link:
```tsx
{user?.role === 'admin' && (
  <button onClick={() => navigate('/app/admin/users')}>
    <Shield /> Admin Panel
  </button>
)}
```

---

## File Summary

| File | Action | Description |
|------|--------|-------------|
| `src/lib/auth.ts` | Edit | Add `role`, `subscription_tier` to `User` |
| `src/lib/api.ts` | Edit | Add `adminApi` + `usageApi` + types |
| `src/components/AdminGuard.tsx` | **New** | Role-based route guard |
| `src/pages/AdminUsers.tsx` | **New** | Admin users table + stats + platform usage |
| `src/components/UserUsageDrawer.tsx` | **New** | Per-user token usage with project filter |
| `src/App.tsx` | Edit | Add `/app/admin/users` route |
| `src/pages/Settings.tsx` | Edit | Conditional admin link |

---

## UI Component Usage (all already in `components/ui/`)

| Component | Usage |
|-----------|-------|
| `table.tsx` | Users table + usage logs table |
| `dialog.tsx` | Edit user (role/tier) dialog |
| `drawer.tsx` | User usage detail drawer |
| `select.tsx` | Period, project, tier, role selectors |
| `badge.tsx` | Role/tier status badges |
| `tabs.tsx` | Tab between Users / Platform Usage |
| `pagination.tsx` | Users + logs pagination |
| `toggle-group.tsx` | Usage type filter |
| `scroll-area.tsx` | Scrollable content areas |
| `input.tsx` | Search box |
| `separator.tsx` | Section dividers |

---

## Implementation Order

1. `auth.ts` — add role fields (2 min)
2. `api.ts` — add `adminApi` + `usageApi` (5 min)
3. `AdminGuard.tsx` — create guard (2 min)
4. `UserUsageDrawer.tsx` — the token usage drawer with project filter (15 min)
5. `AdminUsers.tsx` — main page wiring everything (15 min)
6. `App.tsx` — add route (1 min)
7. `Settings.tsx` — add admin link (2 min)

---

## API Reference (existing backend endpoints)

### Admin Users
```
GET  /admin/users?limit=50&offset=0
     → { users: [{id, email, name, role, subscription_tier, created_at}], total, limit, offset }

PUT  /admin/users/{id}   body: { role?, subscription_tier? }
     → { success, user: {id, email, name, role, subscription_tier} }

POST /admin/users/{id}/reset-limits
     → { success, message }

GET  /admin/stats
     → { total_users, total_projects, total_sessions, total_messages, users_by_tier, users_by_role }
```

### Token Usage
```
GET  /admin/usage?period=month
     → { period, total_tokens, input_tokens, output_tokens, count, unique_users,
         by_type: { ai_chat: {total_tokens, count}, ... },
         top_users: [{user_id, email, name, total_tokens, count}] }

GET  /admin/usage/logs?user_id=X&project_id=Y&usage_type=Z&limit=50&offset=0
     → { logs: [{id, user_id, project_id, session_id, usage_type, description,
                 input_tokens, output_tokens, total_tokens, model, created_at}],
         total, limit, offset }

GET  /projects/{id}/usage?period=all
     → { project_id, period, total_tokens, input_tokens, output_tokens, count }
```

### Constants
```
VALID_ROLES = ["user", "admin"]
VALID_TIERS = ["free", "pro", "dream"]
VALID_USAGE_TYPES = ["ai_chat", "project_create", "ai_completion"]
```
