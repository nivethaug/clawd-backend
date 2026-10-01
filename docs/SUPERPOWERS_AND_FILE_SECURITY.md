# DreamAgent Backend — Architecture & Recent Changes

Last updated: 2026-10-01

## Platform Architecture

```
Main VPS (dreamagent.cloud)              Worker VPS (187.55.225.39)
├── clawd-backend (:8000)                ├── project containers (per-user)
├── tools-api (:8004)                    ├── clawd-worker-api (:8003)
├── dreamagent-mcp (mcp.dreamagent.cloud)├── project backends (PM2 + bwrap)
├── postgres                             └── project frontends (PM2)
├── nginx (api.dreamagent.cloud)
└── /workspaces/user_X/  ← partial strays only

Project files (source code, uploads, outputs) live on the WORKER.
Main VPS proxies file/chat requests to the worker via
project_proxy_middleware (marker-based routing).
```

## Superpowers (tools-api)

Account-level AI tools. Enable once at `/app/superpowers`, use from any project via chat.

### Endpoints (all under `/tools/`)

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /me/tools` | session/API key | Catalog + enabled state + usage |
| `PUT /me/tools/{key}` | session/API key | Enable/disable (account-wide) |
| `POST /projects/{id}/tools/{key}/execute` | session/API key/X-Project-Secret | Submit job (async) |
| `GET /projects/{id}/tools/{key}/jobs` | * | Job history |
| `GET /projects/{id}/tools/{key}` | * | Project-scoped tool state |
| `PUT /projects/{id}/tools/{key}` | * | Project-scoped enable |
| `GET /jobs/{id}` | * | Job status poll |
| `GET /jobs/{id}/file` | * | Download output bytes |
| `GET /projects/{id}/outputs` | * | List generated files |
| `GET /projects/{id}/outputs/{name}` | * | Download output by name |
| `POST /projects/{id}/files` | * | Upload input file |
| `GET /health` | public | Health check |

### Auth (3 paths)

1. **Session token** — `Authorization: Bearer <auth_tokens.token>` (app UI)
2. **User API key** — `Authorization: Bearer <sha256-checked api_keys.key>` (external code)
3. **X-Project-Secret** — `X-Project-Secret: <projects.secret_key>` (generated app backends)

### Tools catalog

| Key | Type | Binding | Ops |
|---|---|---|---|
| `song` | paid | song-api (RunPod) | generate(prompt, style?, duration?, vocals?) |
| `image-gen` | paid | openrouter (FLUX.2 Klein) | generate(prompt, size?) |
| `video-gen` | paid | song-api (Remotion) | generate(prompt, style?, images?, theme?) |
| `voiceover` | paid | song-api | generate(file?, text, language, bed?) |
| `lip-sync` | paid | openrouter (HeyGen) | generate(image, audio, duration) |
| `voice-clone` | paid | voice-api (Seed-VC) | convert(source_audio, target_voice) |
| `ffmpeg` | free | voice-api | extract_audio, trim, audio_convert, replace_audio, merge, burn_subtitles |
| `whisper` | free | local (faster-whisper) | transcribe(file, format?, language?) |
| `sharp` | free | local (sharp) | process(file, op, width?, height?, format?) |
| `pdf` | free | local (pypdf) | merge, split, extract_text, create |
| `remotion` | free | song-api (Remotion) | render(images, hook_lines?, duration_seconds?, format?) |

### Output delivery (pull-model)

Outputs land in `<project_path>/tools-output/` on the tools-api host.
Consumer apps on other machines MUST download over HTTP:

```
GET /tools/jobs/{job_id}/file          → raw bytes
GET /tools/projects/{id}/outputs       → list all output files
GET /tools/projects/{id}/outputs/{name} → download by filename
```

Never assume local filesystem access to `tools-output/` — the consumer
may be on a different machine.

## Agent Recipe (superpowers integration)

Every edit-chat prompt (all 5 project types) includes a SUPERPOWERS block
teaching the agent to integrate enabled tools. Key rules:

1. **Backend only** — tool calls go through the app's backend, never frontend
2. **Env vars from .env file** — `DREAMAGENT_TOOLS_URL`, `DREAMAGENT_PROJECT_SECRET`, `PROJECT_ID`
3. **Auth is X-Project-Secret only** — never Bearer, never token exchange
4. **Upload input files first** — `POST /tools/projects/{id}/files` (multipart)
5. **Execute** — `POST /tools/projects/{id}/tools/{tool}/execute`
6. **Poll** — `GET /tools/jobs/{job_id}` until `completed` or `error`
7. **Download** — `GET /tools/jobs/{job_id}/file` (or `/outputs/{name}`)
8. **Save locally** — write bytes to project `tools-output/`

## File Security (file_utils.py)

All file reads/writes go through `FileUtils` — enforced on editor API,
MCP tools, and any future file surface.

| Guard | Scope |
|---|---|
| Path traversal | `commonpath` containment (sibling-dir bug fixed) |
| Write denylist | `.env`, `.git/`, `id_rsa`, `id_ed25519`, `.ssh/`, `.npmrc`, `.pypirc`, `authorized_keys` |
| Read denylist | Same as write denylist — reads blocked too |
| Write size cap | 2 MB per file |
| Binary block | Cannot write binary extensions |
| Signature scan | 10 malware rules (web shells, reverse shells, obfuscated exec, miners, cookie exfil, base64 blobs) |
| Dependency guards | package.json: install scripts blocked, typosquat check on new deps. requirements.txt: same |
| AI review | Z.ai → OpenRouter (`typesafe/jev-router`) classifies executable code writes >800 chars. Fail-open. |

## MCP Server (mcp.dreamagent.cloud)

Exposes DreamAgent to external AI (ChatGPT, Claude, Cursor).

### Tools

| Tool | Write? | Free plan? | Purpose |
|---|---|---|---|
| `dreamagent_list_projects` | read | ✅ | List user's projects |
| `dreamagent_list_superpowers` | read | ✅ | Catalog + enabled state |
| `dreamagent_list_files` | read | ✅ | Project file tree |
| `dreamagent_read_file` | read | ✅ | File content |
| `dreamagent_get_file_diff` | read | ✅ | Git diff vs last commit |
| `dreamagent_get_project_status` | read | ✅ | Creation/deploy status |
| `dreamagent_list_project_env` | read | ✅ | Env variables |
| `dreamagent_list_global_integrations` | read | ✅ | Saved credentials |
| `dreamagent_list_sessions` | read | ✅ | Chat sessions |
| `dreamagent_get_chat_status` | read | ✅ | Chat run status |
| `dreamagent_get_edit_progress` | read | ✅ | Edit progress |
| `dreamagent_write_file` | write | Pro only | Overwrite/create file |
| `dreamagent_delete_file` | write | Pro only | Delete file |
| `dreamagent_build_publish` | write | Pro only | Rebuild + deploy |
| `dreamagent_chat` | write | ✅ | Send edit instruction to agent |
| `dreamagent_create_project` | write | ✅ | Create new project |
| `dreamagent_create_session` | write | ✅ | New chat session |
| `dreamagent_release_project_lock` | write | ✅ | Release project lock |
| `dreamagent_cancel_chat` | destructive | ✅ | Cancel running chat |

### Paid gating

Write/delete/publish tools check `GET /api/billing/summary` → `plan.slug`.
Free accounts get a friendly upgrade message. Fail-open on billing API errors.

### Security

- User's API key travels client → MCP endpoint only (never to the external model)
- Generic exception fallback on all tools (no raw tracebacks/URLs to the model)
- File tools reuse the same `FileUtils` guards as the in-app editor

## Project Proxy (main ↔ worker routing)

`services/project_proxy.py` — middleware that forwards requests to the
worker when files aren't local.

**Routing is marker-based**: a local directory counts as main-hosted only
if it contains a real project marker (`project.json`, `.git`, `backend/`,
`frontend/`, `telegram/`, `discord/`, `scheduler/`). Partial stray dirs
(tools-output, uploads, logs) are ignored — the request proxies to the worker.

This prevents tools-api output writes (which land on main) from hijacking
worker-homed projects.

## Env Injection (worker project backends)

Every project's `backend/.env` (or `telegram/.env` etc.) receives:

```
DREAMAGENT_TOOLS_URL=https://api.dreamagent.cloud
DREAMAGENT_PROJECT_SECRET=<projects.secret_key>
PROJECT_ID=<projects.id>
```

Injected by `_configure_backend_env` (infrastructure_manager.py) and
backfilled across all existing projects via the backfill script.

## Key Files

| File | Purpose |
|---|---|
| `file_utils.py` | All file guards (security, traversal, scanning) |
| `services/project_proxy.py` | Main↔worker routing middleware |
| `acp_chat_handler.py` | Edit agent (prompts, superpowers recipe) |
| `infrastructure_manager.py` | Project setup, env injection |
| `services/ai/openrouter_client.py` | LLM client (create chat, ZAI fallback) |

## Recent Commits (this session)

- `0692b10` — agent recipe: input-file upload step
- `9cf050d` — agent recipe: outputs listing endpoint
- `0692b10` — agent recipe: X-Project-Secret-only auth, no-discovery rule
- `fcd7bbd` — file_utils: Layer 3 dependency guards + Layer 4 Qwen review
- `e82649a` — file_utils: traversal fix, denylist, signature scan
- `3873f5a` — file_utils: DELETE endpoint + GET files/diff
- `8a45a37` — proxy: marker-based main-vs-worker routing
- `794b2d3` — env injection: DREAMAGENT_TOOLS_URL/PROJECT_SECRET/PROJECT_ID
