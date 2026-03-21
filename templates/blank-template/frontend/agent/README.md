# Agent Guide - Frontend Code Navigation & Modification

This folder helps AI assistants understand and modify the React/Vite frontend efficiently.

## AI Index Files

| File | Purpose | When to Update |
|------|---------|----------------|
| `ai_index/symbols.json` | Components, hooks, functions with line numbers | After adding/editing/removing any code |
| `ai_index/modules.json` | Logical module groupings | After adding new files/folders |
| `ai_index/dependencies.json` | Import relationships | After changing imports |
| `ai_index/summaries.json` | Semantic descriptions per file | After significant changes |
| `ai_index/files.json` | File metadata (lines, routes) | After adding/removing files |

## Frontend Structure

```
src/
├── App.tsx          # Routes configuration
├── main.tsx         # Entry point
├── pages/           # Page components (route targets)
├── components/      # Reusable components
│   └── ui/          # Shadcn UI primitives (DO NOT MODIFY)
├── layout/          # Layout wrappers
├── hooks/           # Custom React hooks
├── lib/             # Utility functions
│   └── api-config.ts  # API endpoints configuration
├── services/        # API service layer
│   └── database.ts  # Backend API client
└── index.css        # Global styles
```

---

## 🌐 API Integration

### API Configuration

**File:** `src/lib/api-config.ts`

Central configuration for all API endpoints. Base URL uses `{domain}` placeholder that gets replaced during deployment.

```typescript
import { API_ENDPOINTS, getApiUrl } from "@/lib/api-config";

// Get full URL for an endpoint
const loginUrl = getApiUrl(API_ENDPOINTS.auth.login);
// → "https://{domain}-api.dreambigwithai.com/api/auth/login"
```

**Available Endpoints:**
| Endpoint | Path |
|----------|------|
| Health | `/health` |
| Auth Register | `/api/auth/register` |
| Auth Login | `/api/auth/login` |
| Auth Logout | `/api/auth/logout` |
| Auth Me | `/api/auth/me` |
| Users Profile | `/api/users/profile` |

### Database Service

**File:** `src/services/database.ts`

Service layer for backend API communication with built-in auth token handling.

```typescript
import { authService, userService, healthService } from "@/services/database";

// Health check
const { success, data } = await healthService.check();

// Login
const result = await authService.login(email, password);
if (result.success && result.data) {
  localStorage.setItem("auth_token", result.data.token);
}

// Get user profile
const { data: user } = await userService.getProfile();

// Create CRUD service for any resource
const postsService = createCrudService<Post>("posts");
const { data: posts } = await postsService.list({ page: 1 });
```

**Available Services:**
| Service | Methods |
|---------|---------|
| `healthService` | `check()` |
| `authService` | `register()`, `login()`, `logout()`, `me()`, `refresh()` |
| `userService` | `getProfile()`, `updateProfile()`, `getById()`, `list()` |
| `createCrudService<T>()` | `list()`, `getById()`, `create()`, `update()`, `delete()` |

### How to Call Backend API

**Option 1: Use Pre-built Services (Recommended)**
```typescript
import { authService } from "@/services/database";

const handleLogin = async (email: string, password: string) => {
  const result = await authService.login(email, password);
  if (result.success) {
    // Token automatically stored, user data in result.data
  }
};
```

**Option 2: Use Generic API Helper**
```typescript
import { api } from "@/services/database";
import { API_ENDPOINTS } from "@/lib/api-config";

const customCall = async () => {
  const result = await api.post("/api/custom-endpoint", { data });
};
```

**Option 3: Create New Service**
```typescript
import { createCrudService } from "@/services/database";

interface Product {
  id: number;
  name: string;
  price: number;
}

const productService = createCrudService<Product>("products");

// Now you have:
// productService.list(), productService.getById(id)
// productService.create(data), productService.update(id, data)
// productService.delete(id)
```

---

## How to Add New Page

### 1. Read existing pattern
```
Read: ai_index/symbols.json → Find "Welcome" component as reference
```

### 2. Create page component
```tsx
// src/pages/Dashboard.tsx
export default function Dashboard() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
    </div>
  );
}
```

### 3. Add route in App.tsx
```tsx
import Dashboard from "./pages/Dashboard";

// Inside <Routes>
<Route path="/dashboard" element={<Dashboard />} />
```

### 4. Update AI Index
Add to `ai_index/symbols.json`:
```json
"Dashboard": {
  "type": "component",
  "file": "src/pages/Dashboard.tsx",
  "start_line": 1,
  "end_line": 8,
  "module": "pages",
  "description": "Dashboard page component"
}
```

---

## How to Add New Component

### 1. Create component file
```tsx
// src/components/UserCard.tsx
interface UserCardProps {
  name: string;
  email: string;
}

export default function UserCard({ name, email }: UserCardProps) {
  return (
    <div className="p-4 border rounded-lg">
      <h3 className="font-semibold">{name}</h3>
      <p className="text-sm text-muted-foreground">{email}</p>
    </div>
  );
}
```

### 2. Import and use where needed
```tsx
import UserCard from "@/components/UserCard";
```

### 3. Update AI Index
Add to `ai_index/symbols.json`

---

## How to Edit Existing Page/Component

### 1. Find the component
```
Read: ai_index/symbols.json → Search for component name
```

### 2. Navigate to file and lines
```
symbols.json gives you: file path + start_line + end_line
```

### 3. Make changes

### 4. Update AI Index
Update line numbers if they changed.

---

## How to Remove Page/Component

### 1. Find in `ai_index/symbols.json`

### 2. Delete the file

### 3. Remove import and route from App.tsx (if page)

### 4. Update AI Index
- Remove entry from `ai_index/symbols.json`
- Remove from `ai_index/files.json`
- Update `ai_index/dependencies.json`

---

## Quick Reference: AI Index Update Checklist

| Action | symbols | modules | dependencies | summaries | files |
|--------|:-------:|:-------:|:------------:|:---------:|:-----:|
| Add page/component | ✅ | - | - | - | - |
| Edit page/component | ✅ | - | - | - | - |
| Remove page/component | ✅ | - | - | - | - |
| Add new folder | ✅ | ✅ | - | ✅ | ✅ |
| Change imports | - | - | ✅ | - | - |

---

## Pages Folder

`pages/` contains YAML definitions for planned pages:

```yaml
# pages/dashboard.yaml
path: /dashboard
component: Dashboard
auth: required
layout: Layout
```

Use this to plan pages before implementation.

---

## Important Rules

1. **NEVER modify `components/ui/`** - These are Shadcn primitives
2. **Always use `@/` imports** - Configured in tsconfig
3. **Use Tailwind classes** - No inline styles or CSS files
4. **Run `npm run build`** - Verify changes compile before committing

---

## 🚀 How to Publish Frontend

### Quick Publish (Recommended)

From the `frontend/` directory, run:

```bash
python3 buildpublish.py
```

This single command:
1. Cleans Vite caches
2. Removes stale node_modules
3. Runs `npm install` (with dev dependencies)
4. Runs `npm run build`
5. Verifies dist/ directory
6. Fixes file permissions (755/644)
7. Cleans up node_modules (saves ~280MB)

### Output Example

```
==================================================
CLEAN VITE CACHES
==================================================
✓ Cleaned 0 cache directories

==================================================
NPM INSTALL
==================================================
✓ npm install completed (including dev dependencies)

==================================================
NPM RUN BUILD
==================================================
✓ npm run build completed

==================================================
VERIFY DIST
==================================================
✓ Dist verified: 6 items, index.html: 1203 bytes

==================================================
✓ BUILD & PUBLISH COMPLETE
==================================================
```

### Options

| Flag | Description |
|------|-------------|
| `--skip-install` | Skip npm install |
| `--skip-build` | Skip npm run build |
| `--no-cleanup` | Keep node_modules after build |
| `--project-name` | PM2 app name (uses `{project_name}` placeholder) |
| `--restart` | Restart PM2 frontend service after build |

### With PM2 Restart

```bash
python3 buildpublish.py --restart
# Restarts {domain}-frontend PM2 process
```

### When to Use

| Scenario | Command |
|----------|---------|
| After code changes | `python3 buildpublish.py` |
| Deploy to production | `python3 buildpublish.py --restart` |
| Quick rebuild (deps cached) | `python3 buildpublish.py --skip-install` |
| Just install deps | `python3 buildpublish.py --skip-build --no-cleanup` |
