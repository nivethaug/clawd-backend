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
└── index.css        # Global styles
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
