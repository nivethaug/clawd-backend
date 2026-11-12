# Agent Dashboard — frontend/ AI index

This agent's public website. **Frontend-only**: React (Vite + Tailwind), built
to static files and served by nginx. There is NO backend and NO dev server —
never create one.

## ⚠️ DATA RULE (hard requirement)

**ALL data comes from `AGENT_STATUS_URL`** (`src/lib/config.ts`) — this
agent's own jobs, logs, state, and document collections. Nothing else.

- NEVER call external APIs, third-party services, or other backends
- NEVER use localhost / relative `/api` fetches — there is no backend here
- NEVER hardcode/mock data that should come from the endpoint
- The agent's handlers write documents via `storage.py db` server-side; those
  collections appear in the status payload automatically


## 🎨 DESIGN SYSTEM (warm ivory / sage / teal — keep it)

The dashboard uses a light, friendly palette. When adding pages or components,
stay inside it:

- Background warm ivory `#F5F1E8` · cards off-white `#FFFEFA` · borders `#E8E2D8`
- Primary teal `#168F86` · accent sage `#A8DCC0` · text charcoal `#202522`
- Rounded 12–18px (`rounded-xl`/`rounded-2xl`), soft shadows (`shadow-soft`,
  `shadow-lift` on hover), font: Inter
- Use the kit in `src/components/ui.tsx` (StatCard, StatusPill, ActiveBadge,
  Section, Empty, TimeAgo) and the entrance helpers from `index.css`
  (`.anim-card-in` + inline `animationDelay`, `.anim-activity-in`,
  `.anim-check-pop`)
- The animated background (waves + spheres + robot at `public/robot.gif`)
  lives in `src/components/DashboardBackground.tsx`, mounted once in App.tsx.
  Content sits above it via the `relative z-10` wrapper — new pages render
  inside `<main>` and automatically sit above the background.
- Micro-interactions: 200ms transitions, hover lifts, `active:scale-95` on
  buttons, pulse dots via `.animate-pulse-soft`. NEVER add animation
  libraries — CSS only. All motion must respect `prefers-reduced-motion`
  (handled by the kit classes).

## Structure

```
src/
  lib/config.ts        AGENT_STATUS_URL + shared types (AgentStatus, AgentJob…)
  lib/agentDb.ts       getCollection(name, {limit}) → latest documents
  hooks/useAgentStatus.ts  15s polling hook: {data, error, loading, refresh}
  components/ui.tsx    StatCard, StatusPill, TimeAgo, Section
  pages/
    index.ts           PAGE REGISTRY — nav is built from this
    Dashboard.tsx      default page: stats, jobs, activity, collections, state, trigger
  App.tsx              shell + nav (reads the registry)
  main.tsx, index.css  entry + dark theme tokens (CSS variables)
```

## Adding a page (the standard request: "add a page that shows X")

1. Create `src/pages/X.tsx`, default-export a component
2. Register it in `src/pages/index.ts`:
   `{ name: "x", label: "X", component: X }`
3. Use `useAgentStatus()` for jobs/logs/state, `getCollection("name")` for
   agent data. Reuse `StatCard` / `StatusPill` / `TimeAgo` / `Section`.

## Deploy

```bash
cd frontend && python3 buildpublish.py
```

Builds `dist/` and reloads nginx — the site is live immediately after.

## Conventions

- Dark theme via the CSS variables in `index.css`; use Tailwind semantic
  classes (`bg-card`, `text-muted-foreground`, `border`), not raw colors
- Keep tables responsive (`overflow-x-auto`), empty states for no data
- This file is for YOU (the editing agent) — update it when you add pages
  or change the data shape
