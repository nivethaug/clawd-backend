# Nango self-hosted spike (deployment-only evaluation)

Goal: verify the FREE self-hosted edition contains what DreamAgent needs
(OAuth flows + token refresh + proxy + custom API-key providers + webhooks)
before writing any DreamAgent integration code.

The `docker-compose.yaml` here is Nango's pristine file with exactly three
changes: postgres/redis not published (host 5432 belongs to
dreampilot-postgres; redis must never be public), and the server ports
bound to 127.0.0.1 (3003 API/dashboard, 3009 connect UI) until the
nginx/auth phase.

## Deploy (on the main VPS)

```bash
cd /opt/nango   # existing clone of NangoHQ/nango

cd /root/clawd-backend && git pull
cp scripts/nango-spike/docker-compose.yaml /opt/nango/docker-compose.yaml

# Required env (Nango reads .env next to the compose file)
cat > /opt/nango/.env <<'EOF'
NANGO_ENCRYPTION_KEY=__RUN__openssl_rand_hex_32__
NANGO_DASHBOARD_USERNAME=admin
NANGO_DASHBOARD_PASSWORD=__SET_A_STRONG_ONE__
EOF
nano /opt/nango/.env   # fill the two placeholders

cd /opt/nango
docker compose down --remove-orphans
docker compose up -d && sleep 25
docker compose ps
curl -s -o /dev/null -w "health: HTTP %{http_code}\n" http://127.0.0.1:3003/api/v1/health
docker ps --format '{{.Names}}: {{.Ports}}' | grep nango
```

Expected: 3 containers Up; published ports ONLY `127.0.0.1:3003` and
`127.0.0.1:3009`; health 200/204.

## Spike checklist (see conversation runbook)

1. Browser via SSH tunnel `-L 3003:127.0.0.1:3003` → http://localhost:3003
   → dashboard login (NANGO_DASHBOARD_*) → dev environment secret key.
2. Demo OAuth round-trip (`github-demo` provider, Nango's shared test app).
3. `GET /connection` token retrieval, `POST /proxy` authenticated call,
   custom API-key provider (coingecko), resource + feature-gate checks.
4. GO/NO-GO before any DreamAgent code.
