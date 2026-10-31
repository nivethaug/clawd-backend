# Backend Security Review — 2026-10-14

**Scope:** clawd-backend (app.py ~18.9k lines, api/, services/, utils/) + tools-api.
**Method:** four parallel deep audits (auth/authz, injection surfaces, secrets & data exposure, uploads/webhooks/payments/git pipeline), live deployment verification on both VPS, and manual spot-verification of every Critical finding in source.
**Mode:** READ-ONLY review — no code was changed. Live probing was limited to harmless GETs.
**Status snapshot:** findings reflect the tree as of commit `41f5eca` (main) / deployed 2026-10-14.

---

## 🔴 CRITICAL — LIVE-CONFIRMED, exploitable from the public internet today

### LIVE-1. `/internal/*` admin surface exposed on worker VPS port 8003
- Worker VPS (187.55.225.39) runs the **entire app** on `0.0.0.0:8003` (`start-worker-api.sh`), and the host has **no firewall** — `iptables` INPUT policy `ACCEPT`, zero rules (verified live).
- The `/internal` guard (`app.py:2271-2293`) allows any request that carries **no** `X-Forwarded-For` header when `INTERNAL_API_SECRET` is unset (it is optional). Direct internet connections send no XFF → guard passes as "direct internal call".
- **Live proof (read-only):** `curl http://187.55.225.39:8003/internal/custom-domain/server-ip` → `HTTP 200 {"ip":"187.55.225.39"}` from the public internet.
- Exposed alongside it (one POST away for anyone):
  - `POST /internal/delete-user-data` (`app.py:7037-7124`) — wipes any user's `/workspaces/user_{id}`, PM2 processes, nginx configs, by arbitrary `user_id`.
  - `POST /internal/pm2-restart` (`app.py:6924-6994`) — restarts any PM2 app **and pip-installs its requirements.txt into the shared platform venv**; IP filter accepts all RFC1918 sources (docker bridge qualifies).
  - `POST /internal/email/send` (`app.py:2306-2346`) — open SMTP relay (60/h/project cap only).
  - `POST /internal/scrape` (`app.py:7141-7266`) — internal-network SSRF (see HIGH-2).
  - `POST /internal/chat-execute` (`app.py:7343-7365`) — "No IP guard" per its own comment.
- **Fix:** firewall 8003 to the main VPS IP only AND make `X-Internal-Secret` mandatory (fail closed when unset). Never pip-install caller-controlled requirements into the shared venv.

---

## 🔴 CRITICAL (code-level; source-verified manually)

### C-1. `PUT /projects/{project_id}/env` — no ownership check (cross-tenant env tampering)
- `app.py:7444-7580`: `user_id = get_user_id_from_token(...)` is extracted but **never compared to the project owner**. Writes/deletes env keys via `env_manager` (pure `WHERE id = ?`) and restarts the victim's PM2 process.
- Exploit: any authenticated user overwrites a victim's `TELEGRAM_BOT_TOKEN` / webhook URLs → victim's bot traffic ships to the attacker.
- Contrast: `/env/reveal` (`app.py:7599-7613`) checks ownership correctly — the check was missed here.
- Related: `GET /projects/{id}/env` (`app.py:7372-7441`) also lacks the check — values are masked, but key names/project metadata leak cross-tenant (recon for C-1).

### C-2. `POST /projects/{project_id}/clone` — no source-project gate (cross-tenant source theft)
- `app.py:4712-4791`: only the *cloner's* quota is checked; source fetched with bare `SELECT * FROM projects WHERE id = ?` (`app.py:4736-4739`); full workspace copied by `_copy_project_files` (`app.py:4232+`), including `backend/data/uploads` user documents.
- Exploit: enumerate sequential project ids → clone any private project → read via `/projects/{id}/files/...`. (`.env` secrets are stripped by `_sanitize_clone_env` — otherwise this would allow secret theft too.)
- Contrast: `/clone-requirements` (`app.py:4942-4953`) enforces owner/admin/public-gallery properly.

### C-3. Live secrets and PII committed to the git repo
- Real Telegram bot token hardcoded as a default in `tests/test_scheduler_channels.py:35` (file is git-tracked).
- `clawdbot_adapter.db` tracked in git — contains `users` (emails, password columns), `projects` (46), `sessions`, `messages` (chat content).
- Hardcoded `CLAWDBOT_TOKEN` fallback value in `chat_handlers.py:17` (sent as Bearer to the internal agent service).
- `log.txt` (LLM response previews) and `mcp_test_stderr.log` tracked despite gitignore entries (force-added historically).
- **Fix:** rotate the Telegram token and CLAWDBOT token, remove files, purge from git history, treat `.gitignore` as authoritative.

---

## 🟠 HIGH

1. **GitHub OAuth `state` forgeable, no PKCE** — authorize URL builds `state = f"{user_id}:{secrets.token_hex(8)}"` (`app.py:11964`) but the callback (`app.py:11971-12007`) only parses `user_id`; the random half is never validated, no session binding, no PKCE (`github_oauth_service.py:44-70`). Exploit: attacker binds their own GitHub as the victim's connection → victim's "Export to GitHub" pushes private code to the attacker's account.
2. **`/internal/scrape` = unauthenticated internal SSRF** — caller-IP guard only; URL check is `startswith("http")` (`app.py:7224`); redirects followed (`app.py:7234`). Reachable from user project sandboxes (NAT via worker IP — per the code's own docstring) → fetch `169.254.169.254`, `127.0.0.1:8003/internal/...` etc.
3. **Scheduler internal bypass trusts the whole XFF chain** — `api/scheduler_router.py:88-127` iterates every client-supplied `X-Forwarded-For` entry against `SCHEDULER_INTERNAL_ALLOWLIST`; nginx appends client XFF. If the allowlist is set, a spoofed header bypasses JWT on all scheduler endpoints (create/modify/run jobs as any project owner).
4. **Custom-domain endpoints check tier but never ownership** — `app.py:7896-7911`, `7950-7967`, `8003+`, `8215+`: any paid user can attach/verify/delete a domain on a victim's project (SSL provisioning + victim nginx rewrite → hijack/DoS).
5. **No brute-force protection on `/auth/login`** — excluded from the rate limiter (`app.py:18184-18188`), no lockout/attempt counting (`app.py:11192-11256`); signup discloses existing emails (`app.py:11158`) → credential stuffing + account enumeration.
6. **Chat images served unauthenticated with predictable names** — `GET /images/chat/{name}` + `/images` StaticFiles mount (`app.py:2375-2390`); names are `session_{session_id}_{YYYYMMDD_HHMMSS}.jpg` (`image_handler.py:38-40`) — sequential id + second-resolution timestamp → cross-tenant image harvesting.
7. **LemonSqueezy webhook: no replay protection / no order dedup** — HMAC-SHA256 + `compare_digest` (`lemonsqueezy_service.py:282-305`) but no timestamp window and `order_created` grants credits with no processed-order guard (`:457-514`). One captured signed body replays N×. (Razorpay is idempotent via `payments.status` — `razorpay_service.py:433-445`.)
8. **Manual commit + rollback force-push skip `guard_push`** — `POST /projects/{id}/commits` (`app.py:16883-16965`) and rollback (`app.py:17836-17857` force-push) push without the secret scan that `_auto_commit_and_push` performs (`app.py:16824-16828`).
9. **Upload path lacks magic-byte validation and malware scan** — uploads trust client `Content-Type` (`app.py:12556-12562`); `_compress_image_bytes` stores raw bytes verbatim when PIL fails to parse (`app.py:12441-12465`); gallery thumbnails written to public `/images` with no decode check (`app.py:12320-12372`); the 10-rule malware/shell scanner (`file_utils.py:50-81`) runs **only** on the AI file-write path, never on uploads.
10. **Session tokens stored plaintext in DB** — `auth_tokens.token` raw (`app.py:11084-11094`, `11238-11243`); read by tools-api too (`tools-api/app/auth.py:37-41`). DB read = account takeover for all live sessions. (API keys correctly SHA-256-hashed.)
11. **Anonymous LLM endpoints** — `/ai/completion{,/stream}` (`app.py:15997-16074`, self-declared anonymous) and `/templates/select` (`app.py:4974-5015`) call Groq unauthenticated and unthrottled → platform LLM budget drain.

## 🟡 MEDIUM

- **IDOR on `messages.id`** — `GET /projects/{id}/commits/{message_id}` (`app.py:17091-17108`) and rollback variant (`app.py:17802-17805`) look up messages without project scoping → cross-tenant message content read. (Log-id variants are correctly scoped: `17118-17123`, `17977-17980`.)
- **`/debug/custom-domain/{id}` unauthenticated** (`app.py:8105-8198`) — leaks subdomain, expected IP, DNS state, nginx `nginx -t` output, SSL paths for any project.
- **SQL via unsanitized db names at deletion** — `app.py:5307-5330` builds `DROP DATABASE/USER {name}` from `project.json` fallback (`app.py:5695-5698`); creation path sanitizes (`project_creation_runs.py:879-884`) but the deletion fallback does not → admin-SQL injection via crafted project name when metadata is missing.
- **Credit reservation race** — `services/billing_service.py:290-367` check-then-charge without `FOR UPDATE`/advisory lock (tools-api does it correctly: `tools-api/app/credits.py:58-84`).
- **Scheduler silent sandbox degradation** — `services/scheduler/execution_engine.py:65`: if the sandbox script is missing, user executors run in-process with full platform access (log warning only).
- **Google OAuth** — audience check skipped when `GOOGLE_CLIENT_ID` unset (`app.py:11684-11702`); legacy `tokeninfo` endpoint; auto-linking to password accounts by email match without `password IS NULL` guard (`app.py:11734-11751`).
- **`guard_push` pattern coverage thin** — `github_service.py:223-230`: 6 patterns; misses `sk-ant-`, `sk_live_`, `AIza`, Telegram tokens, Razorpay keys, JWTs, DB URLs; skips files >2MB.
- **Admin WS terminal token in URL query** (`api/terminal_router.py:97-114`) — lands in nginx/proxy logs; WS "dangerous command" blocklist trivially bypassed (`:151-153`).
- **Discord webhook lacks timestamp freshness** (`api/discord_webhook.py:49-88`) — Slack's 5-minute window (`api/slack_webhook.py:52`) is the model.
- **tools-api `X-Project-Secret` uses `==`** (`tools-api/app/auth.py:72`) — not constant-time; inconsistent with `compare_digest` everywhere else.
- **`WEBHOOK_DEV_BYPASS`** shared across LS/Razorpay/Telegram verifiers (`lemonsqueezy_service.py:265`, `razorpay_service.py:234`, `telegram_webhook.py:43`) — one mis-set env opens all payment webhooks.
- **Chat content & emails in logs** — `app.py:161-162`, `9372` log user messages; `services/email_service.py` logs recipients; `services/ai/glm_client.py:105` logs upstream error bodies.
- **No password-reset flow exists** (availability gap) — email-verification tokens have no expiry (`app.py:11838-11842`).
- **Token/secret hygiene** — `/health` echoes token prefix (admin-gated, `app.py:13830-13836`); LemonSqueezy key tail logged (`lemonsqueezy_service.py:150,163`); `secure_value.key` (master key for global integrations) not gitignored (`secure_value.py:25`); gh token embedded in URL argv fallback visible in process listings (`github_service.py:476-481`).
- **Scheduler bypass via container egress** — user sandbox traffic NATs via the worker IP (likely allowlisted) — see HIGH-3 chain.

## 🟢 LOW / INFO

- Raw `str(e)` in HTTPException details (e.g. `app.py:7481`, `7519`, `10835`, `16495`) — file paths/OS errors to clients; no stack traces; no `debug=True` anywhere; `/docs` disabled by default.
- CORS `allow_origins=["*"]` on the platform API (`app.py:2243-2249`) — acceptable for header-token auth (`allow_credentials=False`); note generated customer apps get `*` WITH `allow_credentials=True` (`fast_wrapper.py:282-288`).
- Browser-context JS injection via scraper CSS selectors (`services/web_scraper.py:379-431`) — confined to throwaway headless page.
- Admin web terminal = shell=True RCE by design, admin-gated (`services/web_terminal.py:38-45`).
- Project deletion leaves `upload_files` rows + files on disk (`app.py:12612-12629`) — ghost quota, retained content.
- Decompression-bomb PNGs pass gallery caps (no dimension decode).
- Duplicate auth helpers with divergent behavior (`utils/auth_helpers.py:44-49` vs `app.py:11084-11095`).
- Session tokens never expire (`database_postgres.py:1359-1363`); `ADMIN_METRICS_TOKEN` never expires.
- Duplicate `/about` route (`app.py:86-87`) — cosmetic.

---

## ✅ Verified solid (keep and advertise)

- **SQL**: parameterized `?`/`%s` everywhere except the one deletion fallback noted above; ORDER BY/LIMIT constants whitelisted.
- **Path traversal**: `FileUtils.sanitize_path` (realpath + commonpath containment) backs every file endpoint; `.env`/`.git`/key denylist on read+write (`file_utils.py:44-47, 212-264`); server-generated upload filenames; no zip extraction anywhere (no zip-slip).
- **Command execution**: git/npm/pm2/psql calls are argv-lists (no shell); domains validated by regex at every entry (`validate_subdomain`, `DOMAIN_REGEX`) before reuse in PM2/nginx names.
- **Auth primitives**: bcrypt cost 12; 256-bit CSPRNG tokens; API keys SHA-256 at rest, returned once, owner-scoped revocation; admin service token `compare_digest`.
- **Webhooks**: HMAC-SHA256 + `compare_digest`, fail-closed on missing secret, raw-body signing on all four providers; Slack adds a replay window; Discord Ed25519.
- **Payments**: amounts resolved server-side by `variant_id` (never request body); Razorpay idempotent; admin billing gated.
- **Env secrets**: SYSTEM_KEYS hidden at GET/PUT/reveal (verified in code, three layers); reveal owner-gated + audit-logged without values; global integrations encrypted (NaCl SecretBox); env files chmod 600 atomic writes.
- **tools-api**: atomic credits (`pg_advisory_xact_lock` + `FOR UPDATE SKIP LOCKED`), output containment, upload sanitization + 200MB cap.
- **Sandbox**: bwrap PID-namespace isolation with env whitelisting (strips `_PROJECT_SOURCED_KEYS`), no `/root`, no docker.sock.
- **Tenant isolation**: `_require_project_owner`/`_require_session_owner`/`_require_session_key_owner` coverage is broad — the findings above are the endpoints that forgot to call them.
- **Isolation architecture**: per-project Postgres database+user; repos private by default; clone strips secrets; PM2 child env secret-free.

---

## Recommended fix order

| # | Action | Effort |
|---|---|---|
| 1 | **Firewall worker 8003 (main-VPS-IP only) + make `X-Internal-Secret` mandatory; remove pip-install-into-shared-venv** | small |
| 2 | **Rotate leaked tokens (Telegram test token, CLAWDBOT fallback); untrack `clawdbot_adapter.db`/`log.txt`; purge history** | small |
| 3 | Owner checks: `PUT/GET /env`, clone source gate, custom-domain quartet, `/debug/custom-domain` | small |
| 4 | GitHub OAuth state validation (+PKCE); login rate limiting + generic signup response | medium |
| 5 | Upload hardening: magic-byte/PIL-parse mandatory (no raw fallback), malware scan on uploads, gallery decode check | medium |
| 6 | `guard_push` in manual commit + rollback paths; broaden secret patterns | small |
| 7 | Hash session tokens at rest (like API keys); LS webhook dedup + timestamp window | medium |
| 8 | Scope `messages.id` lookups to project; sanitize deletion-path DB names; randomize chat-image filenames | small |
| 9 | Scheduler XFF: trust only the proxy-appended entry; ensure sandbox presence (fail closed) | small |
| 10 | Constants-time `==` → `compare_digest` in tools-api; `/internal/scrape` URL IP filtering; expiry for session/verification tokens | small |

*Report generated by automated + manual review; re-verify after fixes and before external disclosure. Secret values intentionally not reproduced — rotate regardless.*
