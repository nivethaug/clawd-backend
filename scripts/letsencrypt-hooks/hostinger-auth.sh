#!/bin/bash
# Certbot manual-auth hook — places _acme-challenge TXT records via the
# Hostinger DNS API v1 (same API/zone as dns_manager.py). Handles MULTIPLE
# validations on the same challenge name (e.g. a cert covering BOTH
# dreamagent.cloud and *.dreamagent.cloud): tokens accumulate in a state
# file and all of them are written together, so earlier TXT values are
# never overwritten by later hook runs.
#
# Requires: HOSTINGER_API_TOKEN (env or /root/clawd-backend/.env),
# CERTBOT_DOMAIN / CERTBOT_VALIDATION (exported by certbot).

set -u

DOMAIN="${CERTBOT_DOMAIN:-}"
TOKEN="${CERTBOT_VALIDATION:-}"
[ -z "$DOMAIN" ] && { echo "CERTBOT_DOMAIN missing" >&2; exit 1; }
[ -z "$TOKEN" ] && { echo "CERTBOT_VALIDATION missing" >&2; exit 1; }
DOMAIN="${DOMAIN#\*.}"   # wildcard certs pass the bare domain
CHAL="_acme-challenge.${DOMAIN}"

ENV_FILE="${CLAWD_BACKEND_ENV:-/root/clawd-backend/.env}"
API_TOKEN="${HOSTINGER_API_TOKEN:-}"
if [ -z "$API_TOKEN" ] && [ -f "$ENV_FILE" ]; then
    API_TOKEN=$(grep "^HOSTINGER_API_TOKEN=" "$ENV_FILE" | head -1 | cut -d= -f2-)
fi
[ -z "$API_TOKEN" ] && { echo "HOSTINGER_API_TOKEN not found in $ENV_FILE" >&2; exit 1; }

STATE_DIR="/var/lib/letsencrypt-hooks"
mkdir -p "$STATE_DIR"
STATE="${STATE_DIR}/tokens.${DOMAIN}.txt"
echo "$TOKEN" >> "$STATE"

# Build the combined TXT record set (unique tokens from this validation round)
TOKENS_JSON=$(sort -u "$STATE" | python3 -c 'import json,sys; print(json.dumps([t.strip() for t in sys.stdin if t.strip()]))')

STATUS=$(curl -s -o /tmp/acme-dns-out.json -w "%{http_code}" -X PUT \
    "https://developers.hostinger.com/api/dns/v1/zones/${DOMAIN}" \
    -H "Authorization: Bearer ${API_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"overwrite\":true,\"zone\":[{\"name\":\"_acme-challenge\",\"records\":${TOKENS_JSON},\"ttl\":300,\"type\":\"TXT\"}]}")

if [ "$STATUS" != "200" ]; then
    echo "Hostinger TXT write failed (HTTP $STATUS): $(cat /tmp/acme-dns-out.json 2>/dev/null)" >&2
    exit 1
fi

echo "TXT ${CHAL} written (all pending tokens); waiting 20s for the zone..."
sleep 20
