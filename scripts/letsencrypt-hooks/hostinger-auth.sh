#!/bin/bash
# Certbot manual-auth hook — places the _acme-challenge TXT record via the
# Hostinger DNS API v1 (same API/zone as dns_manager.py). Requires:
#   - HOSTINGER_API_TOKEN in the environment or /root/clawd-backend/.env
#   - CERTBOT_DOMAIN / CERTBOT_VALIDATION (exported by certbot)
# Sleeps ~20s after writing so the authoritative zone serves the TXT before
# Let's Encrypt validates.

set -u

DOMAIN="${CERTBOT_DOMAIN:-}"
TOKEN="${CERTBOT_VALIDATION:-}"
[ -z "$DOMAIN" ] && { echo "CERTBOT_DOMAIN missing" >&2; exit 1; }
[ -z "$TOKEN" ] && { echo "CERTBOT_VALIDATION missing" >&2; exit 1; }
DOMAIN="${DOMAIN#\*.}"   # wildcard certs pass the bare domain

ENV_FILE="${CLAWD_BACKEND_ENV:-/root/clawd-backend/.env}"
API_TOKEN="${HOSTINGER_API_TOKEN:-}"
if [ -z "$API_TOKEN" ] && [ -f "$ENV_FILE" ]; then
    API_TOKEN=$(grep "^HOSTINGER_API_TOKEN=" "$ENV_FILE" | head -1 | cut -d= -f2-)
fi
[ -z "$API_TOKEN" ] && { echo "HOSTINGER_API_TOKEN not found in $ENV_FILE" >&2; exit 1; }

STATUS=$(curl -s -o /tmp/acme-dns-out.json -w "%{http_code}" -X PUT \
    "https://developers.hostinger.com/api/dns/v1/zones/${DOMAIN}" \
    -H "Authorization: Bearer ${API_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"overwrite\":true,\"zone\":[{\"name\":\"_acme-challenge\",\"records\":[{\"content\":\"${TOKEN}\"}],\"ttl\":300,\"type\":\"TXT\"}]}")

if [ "$STATUS" != "200" ]; then
    echo "Hostinger TXT write failed (HTTP $STATUS): $(cat /tmp/acme-dns-out.json 2>/dev/null)" >&2
    exit 1
fi

echo "TXT _acme-challenge.${DOMAIN} written; waiting 20s for the zone to serve it..."
sleep 20
