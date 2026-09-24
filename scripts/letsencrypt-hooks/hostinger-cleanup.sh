#!/bin/bash
# Certbot manual-cleanup hook — clears the _acme-challenge TXT record after
# validation (overwrite with an empty record set on that name).

set -u

DOMAIN="${CERTBOT_DOMAIN:-}"
[ -z "$DOMAIN" ] && exit 0
DOMAIN="${DOMAIN#\*.}"

ENV_FILE="${CLAWD_BACKEND_ENV:-/root/clawd-backend/.env}"
API_TOKEN="${HOSTINGER_API_TOKEN:-}"
if [ -z "$API_TOKEN" ] && [ -f "$ENV_FILE" ]; then
    API_TOKEN=$(grep "^HOSTINGER_API_TOKEN=" "$ENV_FILE" | head -1 | cut -d= -f2-)
fi
[ -z "$API_TOKEN" ] && exit 0

curl -s -X PUT \
    "https://developers.hostinger.com/api/dns/v1/zones/${DOMAIN}" \
    -H "Authorization: Bearer ${API_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"overwrite\":true,\"zone\":[{\"name\":\"_acme-challenge\",\"records\":[],\"ttl\":300,\"type\":\"TXT\"}]}" \
    > /dev/null

# Reset the accumulated validation tokens — a fresh renewal starts clean.
rm -f "/var/lib/letsencrypt-hooks/tokens.${DOMAIN}.txt" 2>/dev/null

exit 0
