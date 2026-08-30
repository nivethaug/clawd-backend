# DreamAgent — Environment Checklist (Main VPS · Worker VPS · Wrapper-v2)

> Canonical env files: production reads `/root/clawd-backend/.env.postgres` (set by
> `start-backend.sh`, `start-scheduler.sh`, `start-worker-api.sh` via
> `POSTGRES_ENV_FILE`). Wrapper-v2 runs under PM2 (`ecosystem.config.js`).
> Template reference: `.env.example` / `.env.postgres.example` in each repo.

Legend: 🔴 **required** (no default — service broken/feature off without it) ·
🟡 required-for-feature · 🟢 optional (sensible default)

---

## 1. Main VPS — control API + frontend (`clawd-backend`)

### Core / database
| Var | Status | Purpose / notes |
|---|---|---|
| `USE_POSTGRES` | 🟢 | default `true` |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` | 🟢 | `localhost` / `5432` / `dreampilot` / `admin` |
| `DB_PASSWORD` | 🔴 | Postgres password |
| `PORT` | 🟢 | default `8002` |
| `EXECUTION_MODE` | 🟢 | `local` vs `container` — keep `local` on Main |
| `DREAMAGENT_ROLE` | 🟡 | set **`main`** (default) — used by system metrics |
| `FRONTEND_URL` | 🟢 | default `https://dreamagent.cloud` |
| `IMAGES_BASE_URL` | 🟢 | default `https://api.dreamagent.cloud/images` |
| `ENABLE_API_DOCS` | 🟢 | keep `false` in prod |
| `GLOBAL_INTEGRATIONS_KEY` | 🔴 | encrypts stored integration secrets |
| `INTERNAL_API_SECRET` | 🔴 | internal API auth |
| `SCHEDULER_INTERNAL_ALLOWLIST` | 🟡 | comma list for internal scheduler routes |
| `TRUST_PROXY_AUTH` | 🟡 | only if worker proxies auth headers |
| `ADMIN_METRICS_TOKEN` / `ADMIN_METRICS_USER_ID` | 🟡 | metrics endpoint auth |
| `SHARED_VENV_PATH` | 🟢 | shared venv path |

### Domains / infrastructure
| Var | Status | Purpose / notes |
|---|---|---|
| `DREAM_DOMAIN` | 🟢 | default `dreamagent.cloud` |
| `SERVER_IP` | 🟢 | Main VPS public IP (DNS A records) |
| `HOSTINGER_API_TOKEN` | 🟡 | DNS management (deploys) |
| `GITHUB_ORG` | 🟢 | default `nivethaug` |
| `GITHUB_TOKEN` | 🟡 | repo publishing / export |

### Worker coordination (Main-side only)
| Var | Status | Purpose / notes |
|---|---|---|
| `WORKER_VPS_URL` | 🔴 (with worker) | worker base URL for project proxy |
| `WORKER_PROXY_READ_TIMEOUT` | 🟢 | default `600` |
| `WORKER_VPS_SSH_HOST` / `_USER` / `_KEY` | 🟡 | web terminal SSH to worker |
| `DREAMPILOT_WORKER_API_URL` | 🟡 | worker API URL |

### AI providers
| Var | Status | Purpose / notes |
|---|---|---|
| `OPENROUTER_API_KEY` | 🔴 | main AI provider key |
| `OPENROUTER_BASE_URL` / `_SITE_URL` / `_APP_NAME` | 🟢 | OpenRouter config |
| `PROMPT_ASSISTANT_MODEL` / `_PROVIDER` | 🟢 | prompt-assistant LLM |
| `Z_AI_API_KEY` / `Z_AI_API_BASE` / `Z_AI_MODEL` | 🟡 | GLM / ZAI provider |
| `GROQ_API_KEY` / `GROQ_MODEL` | 🟢 | fallback LLM |
| `ANTHROPIC_API_KEY` | 🟢 | direct Anthropic (rare) |
| `WRAPPER_BASE_URL` | 🟢 | default `http://127.0.0.1:7861` |
| `CHAT_IMAGE_*` (VISION_MODEL etc.) | 🟢 | vision pipeline defaults in code |
| `ACP_USE_GLM` / `ACP_USE_PREPROCESSOR` / `ACP_USE_CLAUDE_AGENT` | 🟢 | pipeline toggles |

### Auth / OAuth / integrations
| Var | Status | Purpose / notes |
|---|---|---|
| `GOOGLE_CLIENT_ID` | 🟡 | Google login (OIDC audience check) |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` / `GITHUB_REDIRECT_URI` | 🟡 | GitHub login |
| `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` / `SLACK_REDIRECT_URI` | 🟡 | Slack OAuth |
| `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` / `SLACK_APP_ID` / `SLACK_INTERACTIONS_SECRET` | 🟡 | Slack control app |
| `DISCORD_CONTROL_BOT_TOKEN` / `DISCORD_PUBLIC_KEY` / `DISCORD_APPLICATION_ID` / `DISCORD_GUILD_ID` / `DISCORD_INTERACTIONS_SECRET` | 🟡 | Discord control bot |
| `TELEGRAM_BOT_TOKEN` | 🟡 | Telegram control bot |
| `TELEGRAM_WEBHOOK_SECRET` | 🔴 pending | webhook verification — **still unset, TODO** |
| `NANGO_URL` / `NANGO_PUBLIC_URL` / `NANGO_SECRET_KEY` | 🟡 | Nango OAuth hub (7 live providers) |

### Billing
| Var | Status | Purpose / notes |
|---|---|---|
| `RAZORPAY_KEY_ID` / `RAZPAY_KEY_SECRET` / `RAZORPAY_WEBHOOK_SECRET` | 🟡 | INR/UPI billing — **setup pending** |
| `LEMONSQUEEZY_API_KEY` / `_STORE_ID` / `_WEBHOOK_SECRET` / `_CUSTOMER_PORTAL_URL` | 🟡 | USD billing |
| `WEBHOOK_DEV_BYPASS` | 🟢 | **never** set in prod |
| `BILLING_CRON_INTERVAL` / `PLAN_CACHE_TTL` | 🟢 | billing tuning |
| `INR_LAUNCH_DISCOUNT` | — | code constant (`razorpay_service.py`), NOT env — 25% India offer |

### Email / monitoring
| Var | Status | Purpose / notes |
|---|---|---|
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_FROM` | 🟢 | defaults point at hostinger |
| `SMTP_PASS` | 🟡 | outbound email |
| `SENTRY_DSN` | 🟡 | error tracking |
| `SENTRY_ENVIRONMENT` / `SENTRY_RELEASE` / sample rates | 🟢 | defaults |

---

## 2. Worker VPS — agents / scheduler / containers (`clawd-backend`)

Per `docs/worker_vps_setup.md` Phase 8. Worker runs `start-scheduler.sh`,
`start-worker-api.sh`, project-creation/session-chat workers, wrapper-v2.

### Database (points at Main VPS)
| Var | Status | Purpose / notes |
|---|---|---|
| `DB_HOST` | 🔴 | **Main VPS private/public IP** (not localhost) |
| `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | 🔴 | same creds as Main |
| `USE_POSTGRES` | 🟢 | `true` |

### Role / execution
| Var | Status | Purpose / notes |
|---|---|---|
| `DREAMAGENT_ROLE` | 🔴 | set **`worker`** |
| `SERVER_IP` | 🔴 | **Worker VPS IP** (DNS A records for project domains) |
| `EXECUTION_MODE` | 🟡 | `container` for sandboxed execution |
| `SCHEDULER_ENABLED` / `_INTERVAL` / `_MAX_WORKERS` / `_JOB_TIMEOUT` | 🟢 | defaults `true`/`10`/`10`/`120` |
| `SCHEDULER_BACKEND_URL` | 🟢 | how executing agents reach control API (default `https://api.dreamagent.cloud`) |
| `BACKEND_URL` | 🟢 | backend self-URL for subprocesses |
| `SHARED_VENV_PATH` | 🟢 | shared venv |

### Durable workers
| Var | Status | Purpose / notes |
|---|---|---|
| `PROJECT_CREATION_WORKER_LOG_LEVEL` / `_POLL_SECONDS` | 🟢 | creation worker |
| `SESSION_CHAT_WORKER_LOG_LEVEL` / `_POLL_SECONDS` | 🟢 | chat worker |
| `PROJECT_CREATION_DURABLE_RUNS` / `SESSION_CHAT_DURABLE_RUNS` | 🟢 | keep `true` |
| `PROJECT_CREATION_FAST_TIMEOUT` / `_OPENCLAW_TIMEOUT` | 🟢 | defaults `3600` / `2700` |

### Agent LLM routing (via wrapper-v2)
| Var | Status | Purpose / notes |
|---|---|---|
| `ANTHROPIC_BASE_URL` | 🔴 | `http://localhost:7861/anthropic-compat` (agent CLIs → wrapper) |
| `ANTHROPIC_AUTH_TOKEN` | 🔴 | OpenRouter key (wrapper validates) |
| `ANTHROPIC_MODEL` | 🟡 | default agent model |
| `ZAI_API_KEY` / `OPENROUTER_API_KEY` | 🔴 | provider keys for wrapper tiers |
| `CHROME_CDP_URL` | 🟢 | headless Chrome endpoint (containers) |
| `PROJECT_PIP_MAX_MB` | 🟢 | package-gate size cap (default 500 MB) |
| `PIP_BLOCKED_PACKAGES` | 🟢 | extra blocked packages (built-in: torch/tensorflow/transformers/nvidia-*…) |
| `WHEELHOUSE_URL` | 🟢 | shared wheel cache dir (`scripts/build-wheelhouse.sh`) |
| `EGRESS_ENFORCE` | 🟡 | `1` = squid allowlist sidecar (`scripts/setup-sandbox-enforcement.sh`) |
| `EGRESS_ALLOWLIST` / `EGRESS_REPLY_MAX_MB` | 🟢 | allowlist domains / per-response body cap (default 200 MB) |
| `PROJECT_DISK_LIMIT_GB` | 🟡 | hard container disk cap (XFS pquota) + reaper soft quota |

### Containers / secrets
| Var | Status | Purpose / notes |
|---|---|---|
| `CONTAINER_IMAGE` / `_NETWORK` / `_MEMORY` / `_CPUS` / `_PIDS_LIMIT` / `WORKSPACE_ROOT` etc. | 🟢 | sandbox defaults in `container_manager.py` |
| `HOSTINGER_API_TOKEN` | 🟡 | per-project DNS |
| `GITHUB_TOKEN` | 🔴 | project repo publishing (**private repos**) |
| `SENTRY_DSN` / `SENTRY_ENVIRONMENT` | 🟡 | error tracking |
| `CLAUDE_RUN_AS_USER` / `CLAUDE_TIMEOUT` / `CODEX_*` / `COPILOT_*` | 🟢 | agent runtime tuning |

⚠️ **Security invariants** (post-incident):
- `OPENROUTER_API_KEY` and other daemon keys are scrubbed from sandbox env
  (`_PROJECT_SOURCED_KEYS` in `nango_client.py` + `backend-sandbox.sh`) — never
  inject provider keys into user-project env.
- Project clones get schema-only DB + blanked env VALUES (`_sanitize_clone_env`).

---

## 3. Wrapper-v2 (port 7861, PM2)

⚠️ **Security:** live API keys are currently committed in `ecosystem.config.js` —
move to env file and rotate.

| Var | Status | Purpose / notes |
|---|---|---|
| `WRAPPER_V2_HOST` | 🟢 | `0.0.0.0` — **firewall this port**, unauthenticated LLM proxy |
| `WRAPPER_V2_PORT` | 🟢 | `7861` |
| `WRAPPER_V2_TIER1_BASE_URL` | 🟢 | ZAI coding endpoint (fallback `ZAI_CODING_BASE_URL`) |
| `WRAPPER_V2_TIER1_API_KEY` | 🔴 | tier-1 key (fallback `ZAI_API_KEY`) |
| `WRAPPER_V2_TIER1_MODEL` / `_TIMEOUT` | 🟢 | `glm-5.1` / `90` |
| `WRAPPER_V2_TIER2_BASE_URL` | 🟢 | OpenRouter (fallback `OPENROUTER_BASE_URL`) |
| `WRAPPER_V2_TIER2_API_KEY` | 🔴 | fallback tier key (fallback `OPENROUTER_API_KEY`) |
| `WRAPPER_V2_TIER2_MODEL` / `_TIMEOUT` | 🟢 | `z-ai/glm-5.1` / `180` |
| `WRAPPER_V2_MODEL_BASE_URL` / `_API_KEY` / `WRAPPER_V2_MODEL` | 🟢 | generic model endpoint |
| `WRAPPER_V2_MAX_CREATE_PAGES` / `_BUILD_TIMEOUT` / `_BROWSER_ROUTE_LIMIT` | 🟢 | `4` / `300` / `2` |
| `WRAPPER_V2_REVERSE_TIERS` / `_AUTO_REVERSE` / `_AUTO_REVERSE_THRESHOLD` | 🟢 | tier failover |
| `WRAPPER_V2_ZAI_QUOTA_WINDOW_HOURS` / `_QUOTA_LIMIT_TOKENS` / `_429_COOLDOWN_MINUTES` / `_TIMEOUT_*` / `_TIMEOUT_COOLDOWN_MINUTES` | 🟢 | ZAI quota/429 handling |
| `WRAPPER_V2_ALLOWED_TOOL_NAMES` / `_MAX_MODEL_TOOLS` / `_OPTIMIZE_SYSTEM_PROMPT` / `_TOOL_DESCRIPTION_MAX_CHARS` | 🟢 | tool config |
| `WRAPPER_V2_LOG_ALL` | 🟢 | verbose logging (off in prod) |

---

## 4. MCP server (optional, port 8800)

| Var | Status | Purpose / notes |
|---|---|---|
| `DREAMAGENT_API_URL` | 🟢 | default `https://api.dreamagent.cloud` |
| `DREAMAGENT_EMAIL` / `DREAMAGENT_PASSWORD` | 🔴 | login-based auth |
| `GOOGLE_CLIENT_ID` | 🟡 | Google OIDC |
| `OAUTH_BASE_URL` / `CLIENTS_FILE` / `TRUSTED_OAUTH_REDIRECTS` | 🟢 | OAuth registry |
| `MCP_HOST` / `MCP_PORT` / `LOG_LEVEL` | 🟢 | `127.0.0.1` / `8800` / `INFO` |

---

## 5. Shared-vs-split summary

| Category | Main only | Worker only | Both |
|---|---|---|---|
| Database | — | — | `DB_*` (worker points at Main IP) |
| Secrets | `GLOBAL_INTEGRATIONS_KEY`, `INTERNAL_API_SECRET`, billing keys, OAuth apps (Google/GitHub/Slack/Discord/Telegram), `NANGO_*`, `SMTP_PASS` | `GITHUB_TOKEN` (publishing), `ANTHROPIC_*` (wrapper routing), `SERVER_IP` (worker IP) | `OPENROUTER_API_KEY`, `ZAI_API_KEY`/`Z_AI_API_KEY`, `HOSTINGER_API_TOKEN`, `SENTRY_DSN` |
| Coordination | `WORKER_VPS_URL`, `WORKER_VPS_SSH_*`, `DREAMPILOT_WORKER_API_URL`, `TRUST_PROXY_AUTH` | `DREAMAGENT_ROLE=worker`, `EXECUTION_MODE=container`, scheduler/worker vars, `CHROME_CDP_URL` | `SENTRY_ENVIRONMENT` |
| Role tag | `DREAMAGENT_ROLE=main` | `DREAMAGENT_ROLE=worker` | — |

## 6. Known pending items

- [ ] `TELEGRAM_WEBHOOK_SECRET` — still unset
- [ ] Razorpay keys + webhook registration (India launch offer live in UI; charging waits on keys)
- [ ] Rotate keys committed in `wrapper-v2/ecosystem.config.js`; move to env file
- [ ] Remove hardcoded `CLAWDBOT_TOKEN` default in `chat_handlers.py:17`
