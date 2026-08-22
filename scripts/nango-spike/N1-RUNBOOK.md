# Nango N1 Deployment Runbook (YouTube OAuth)

Execute on the main VPS. Order matters. Prereq: spike deployment done
(`/opt/nango` running, dashboard accessible).

## 1. DNS + nginx

Create two A records → `195.200.14.37`:
- `nango.dreamagent.cloud`
- `connect.dreamagent.cloud`

nginx (`/etc/nginx/sites-available/nango`):

```nginx
server {
    server_name nango.dreamagent.cloud;
    location / { proxy_pass http://127.0.0.1:3003; proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto https; }
    # 25MB for OAuth code exchange bodies
    client_max_body_size 25m;
}
server {
    server_name connect.dreamagent.cloud;
    location / { proxy_pass http://127.0.0.1:3009; proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto https; }
}
```

```bash
ln -s /etc/nginx/sites-available/nango /etc/nginx/sites-enabled/
certbot --nginx -d nango.dreamagent.cloud -d connect.dreamagent.cloud
nginx -t && systemctl reload nginx
```

Dashboard is login-gated (strong password). Optional hardening: restrict
non-`/oauth/` dashboard paths by IP.

## 2. Nango public URLs

```bash
cat >> /opt/nango/.env <<'EOF'
NANGO_SERVER_URL=https://nango.dreamagent.cloud
NANGO_PUBLIC_SERVER_URL=https://nango.dreamagent.cloud
NANGO_PUBLIC_CONNECT_URL=https://connect.dreamagent.cloud
EOF
cd /opt/nango && docker compose up -d nango-server
curl -s -o /dev/null -w "public nango: HTTP %{http_code}\n" https://nango.dreamagent.cloud/oauth/callback
```

## 3. YouTube OAuth app (one-time)

Google Cloud Console → APIs & Services → Credentials:
- Reuse the existing OAuth client (`GOOGLE_CLIENT_ID`) or create one for
  `dreamagent.cloud`; **create a client secret** if none
- Authorized redirect URI: `https://nango.dreamagent.cloud/oauth/callback`
- Enable **YouTube Data API v3** + **YouTube Analytics API** for the project

## 4. Register the provider in Nango

```bash
SK=305a2e46-2c46-466f-bdc2-46745a8485e1   # dev key (or a fresh one)
GCID=<google client id>  GSEC=<google client secret>
curl -s -X POST https://nango.dreamagent.cloud/integrations \
  -H "Authorization: Bearer $SK" -H "Content-Type: application/json" \
  -d "{\"provider\":\"youtube\",\"unique_key\":\"youtube\",\"credentials\":{\"type\":\"OAUTH2\",\"client_id\":\"$GCID\",\"client_secret\":\"$GSEC\",\"scopes\":\"https://www.googleapis.com/auth/youtube.readonly,https://www.googleapis.com/auth/yt-analytics.readonly\"}}"
```

(Do this in the dev environment first; repeat with the prod environment's
key before launch.)

## 5. DreamAgent backend env

In `/root/clawd-backend/.env`:

```
NANGO_URL=http://127.0.0.1:3003
NANGO_PUBLIC_URL=https://nango.dreamagent.cloud
NANGO_SECRET_KEY=<nango environment secret key — same $SK>
```

Then `git pull && pm2 restart clawd-backend`.

Sanity: `curl -s -H "Authorization: Bearer <dreamagent token>" https://api.../api/integrations/nango/providers`
→ `{"providers":[{"provider":"youtube",...,"connected":false}]}`

## 6. Proof of concept (definition of done)

1. Frontend → Settings → Integrations → **[Connect YouTube]** → Google consent →
   card flips to **✓ Connected as <channel>**
2. Create a scheduler project with a YouTube analytics task; first job run
   gets `YOUTUBE_ACCESS_TOKEN` injected automatically (check
   `pm2 logs clawd-scheduler | grep "injected YOUTUBE_ACCESS_TOKEN"`)
3. Report arrives via the configured channel — user configured nothing else.

## Rollback

Unset `NANGO_SECRET_KEY` in the backend `.env` + restart: nango endpoints
503, Integrations page shows API-key cards only, scheduler injection
no-ops. Nango containers can stay (or `docker compose down`).
