# Registering a New OAuth Provider in Nango

Runbook for adding a one-click OAuth integration (YouTube, Notion, Calendly, …)
to DreamAgent. Three sides must line up:

1. **Provider developer portal** — create the OAuth app (credentials)
2. **Nango** (self-hosted, `http://127.0.0.1:3003` on the main VPS) — register those credentials once
3. **clawd-backend + frontend** — the app-side registry entry

> ⚠️ Self-hosted Nango ships only the protocol *template* per provider
> (authorization/token URLs, proxy base_url). OAuth credentials are always
> YOUR OWN app's — Nango's shared-credentials feature is Nango-Cloud-only.

---

## Step 1 — Create the OAuth app at the provider

| Provider | Portal | Notes |
|---|---|---|
| Calendly | https://developer.calendly.com → My Apps → Create new app | instant, no review; select read-only + scheduling_links/webhook scopes |
| Notion | https://www.notion.so/my-integrations | internal integration is enough |
| GitHub | https://github.com/settings/developers → OAuth Apps | no review |
| Discord | https://discord.com/developers/applications | no review for user auth |
| X (Twitter) | https://developer.twitter.com | needs approved dev account (one-time) |
| Slack | https://api.slack.com/apps | no review (directory listing optional) |
| Google (YouTube/Sheets/Calendar) | https://console.cloud.google.com/apis/credentials | ⚠️ restricted scopes need Google verification + CASA — see the pending-approval queue before promising launch |

**Redirect / callback URI (all providers):**

```
https://nango.dreamagent.cloud/oauth/callback
```

Must match exactly — no trailing slash. A mismatch shows as `redirect_uri`
errors on Connect.

Copy the **Client ID** and **Client Secret** (secrets usually show once;
regenerate if lost).

## Step 2 — Register the credentials in Nango (main VPS, one-time)

```bash
NGSECRET=$(grep '^NANGO_SECRET_KEY' /root/clawd-backend/.env | cut -d= -f2)
CCID=<client id>; CSEC=<client secret>
curl -s http://127.0.0.1:3003/integrations \
  -H "Authorization: Bearer $NGSECRET" -H "Content-Type: application/json" \
  -d '{"provider":"<nango-provider-slug>","unique_key":"<nango-provider-slug>","credentials":{"type":"OAUTH2","client_id":"'"$CCID"'","client_secret":"'"$CSEC"'"}}'
```

Success: response contains `"unique_key":"<slug>"`.

**Do NOT pass `credentials.scopes`** — our Nango version's schema rejects it
(`invalid_union` on `credentials.scopes`, tried as both string and array).
Scopes come from the provider app's own configuration + the template
defaults; verify what's actually granted on the consent screen during the
Connect test.

The `<nango-provider-slug>` is Nango's template name — same as the dict key
in `ENABLED_PROVIDERS` unless an entry overrides `nango_provider` (e.g.
`twitter` → template `twitter-v2`). Find slugs in Nango's catalog:
`GET http://127.0.0.1:3003/providers` (needs auth) or nango.dev integrations
directory.

## Step 3 — App-side entry (clawd-backend, `services/integrations/nango_client.py`)

```python
# ENABLED_PROVIDERS — the card appears in Integrations → Available
"<slug>": {
    "title": "Calendly",
    "category": "Integrations",
    "description": "…one-click <Provider> authorization.",
    "env_token_key": "<PROVIDER>_ACCESS_TOKEN",   # metadata only (vestigial)
    # "nango_provider": "other-template",         # only when slug != template
},

# PROVIDER_EXTRAS — capabilities + examples + gotchas the agent prompt
# receives once a project has the provider connected. Teach URIs/auth
# quirks/pagination here (see "calendly" for a full example).
```

Frontend: add the icon in `muse-companion-app/src/pages/Integrations.tsx`
(`OAuthCard` provider → icon ternary + lucide import).

Deploy: main VPS `git pull && pm2 restart api` + frontend build.

## Step 4 — Verify end-to-end

1. Integrations page → new card → **Connect** → provider consent → ✓ Connected
2. Consent screen shows the expected scopes (this is where scope mistakes surface)
3. In a connected project's session chat, ask the agent to read a simple
   endpoint (e.g. Calendly `users/me`) via the integrations proxy

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `invalid_union` on `credentials.scopes` | remove `scopes` from the payload (see step 2) |
| Connect button errors immediately | Nango integration not registered, or wrong slug — re-run step 2 |
| Provider consent `redirect_uri` mismatch | callback URL differs from step 1's exact string |
| Proxy 502 `No base_url known for provider` | Nango template lacks `proxy.base_url` — that provider can't be proxied as-is; check `GET /providers` entry |
| Connect OK but API 401/403 | scopes actually granted < scopes needed — adjust the provider app's scope selection and reconnect |

## Current provider registry

| ENABLED_PROVIDERS key | Nango template | Status |
|---|---|---|
| youtube | youtube | live (Google-verified app) |
| github | github | live |
| discord | discord | live |
| notion | notion | live |
| twitter | twitter-v2 | live |
| slack | slack | live |
| calendly | calendly | live (registered without explicit scopes) |
| google-sheet | google-sheet | **hidden** until Google verifies the `spreadsheets` restricted scope |
