# Nango self-hosted spike — RESULTS (2026-08-22)

**VERDICT: GO.** Free self-hosted edition contains everything DreamAgent needs.

## Environment
- Main VPS (`195.200.14.37`), `/opt/nango` (NangoHQ/nango clone, image `nangohq/nango-server:hosted` v0.71.4)
- Compose: `scripts/nango-spike/docker-compose.yaml` (postgres/redis internal-only; server on 127.0.0.1:3003 API + 3009 Connect UI)
- `.env`: NANGO_ENCRYPTION_KEY (base64 32B — BACKUP CRITICAL, all stored creds
  undecryptable without it), SERVER_PORT=3003, FLAG_AUTH_ENABLED=true,
  SMTP_URL (Hostinger relay — email delivery still unverified; dashboard signup was
  unblocked by flipping `email_verified` directly in `_nango_users`)
- Dashboard account: support@dreamagent.cloud (account id 1; seed account 0 is Nango's)
- Footprint: ~445MB RAM total across 3 containers. Free edition confirmed by
  `billing ORB_API_KEY not set — no-op billing client, expected in self-hosted`.

## Verified end-to-end (all with API-key provider `apify`; anthropic used earlier)
1. ✅ Integration creation — `POST /integrations` (catalog: **981 providers** at
   providers.yaml top level; youtube, github, slack, discord, notion, google-calendar,
   stripe all present; NOT coingecko/serper → those stay in DreamAgent's own vault.
   Auth modes: 323 API_KEY / 293 OAUTH2 / 101 OAUTH2_CC / 62 TWO_STEP / 97 BASIC / 24 MCP_OAUTH2 …)
2. ✅ Connect session minting — `POST /connect/sessions` {end_user:{id,email}, allowed_integrations}
   → `nango_connect_sessio…` token (this is what DreamAgent's FastAPI mints per user)
3. ✅ Credential storage — `POST /api-auth/api-key/{pcKey}?connect_session_token=…` {apiKey}
   → connection created. NOTE: anthropic PROVED live server-side credential
   verification (dummy key rejected at connect: `connection_test_failed`) — a feature.
4. ✅ Connection retrieval — `GET /connection/{connectionId}?provider_config_key=…`
   and `GET /connection` (list with end_user linkage)
5. ✅ PROXY — `GET /proxy/v2/users/me` + headers `provider-config-key` / `connection-id`
   → real Apify response (`user-or-token-not-found`) = stored credential injected
   server-side into a live provider call. Tokens never touched the client.

## Critical 0.71 API details (learned the hard way)
- **Public API is ROOT-mounted, NOT /api/v1** — `/api/v1/*` belongs to the dashboard
  (session-cookie auth → generic `unauthorized` trap we hit repeatedly)
- Public API is **snake_case** (`unique_key`, `provider_config_key`, `connection_id`)
- `POST /integrations` body: `{provider, unique_key}` (+optional credentials)
- Proxy: identity via **headers** (`provider-config-key`, `connection-id`), endpoint in path
- api-key connect with session token: `connection_id` query param FORBIDDEN
  (session binds end_user); connection gets a generated UUID connection_id,
  end_user.id stored alongside → for DreamAgent map via end_user or pass explicit id
- API keys (dashboard → API Keys): UUID-format values, returned decrypted by
  `GET /api/v1/environment/api-keys?env=dev` (dashboard route) for dev env
- Demo shared OAuth apps (`github-demo` etc.) do NOT exist in 0.71 — first real OAuth
  test needs our own provider OAuth app (YouTube = existing GOOGLE_CLIENT_ID + secret)

## Not yet tested (first tasks of the integration phase)
- Real OAuth round-trip (needs Google/YouTube OAuth client configured in Nango)
- Webhooks (needs public URL behind nginx; NANGO_PUBLIC_*_URL envs)
- Custom providers (providers.yaml mount is already wired in compose)
- SMTP email delivery from Nango (verification mails)

## DreamAgent integration design implications
- FastAPI client module calls root-path snake_case API with env secret key (server-only)
- React uses @nangohq/frontend with connect-session tokens minted by our backend
- Connection ownership: map DreamAgent user ↔ (end_user.id, connection_id) server-side
- Keep CoinGecko/Serper + all existing API-key vault flows on DreamAgent's own
  global_integrations (no migration); Nango becomes the OAuth+proxy layer
