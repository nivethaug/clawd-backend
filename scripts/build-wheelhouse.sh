#!/bin/bash
# Layer 1C — shared wheelhouse: pre-download wheels for the curated
# common-dependencies list into /opt/wheelhouse so sandbox installs hit
# the local cache instead of PyPI (faster, less egress).
#
# Run on the WORKER VPS (and any host running bwrap sandboxes):
#   bash scripts/build-wheelhouse.sh
# Then set in .env.postgres:
#   WHEELHOUSE_URL=/opt/wheelhouse
#
# The wheelhouse must be visible (ro) inside sandboxes/containers —
# container_manager binds it when EGRESS_ENFORCE is on; bwrap sandboxes
# get a --ro-bind (see sandbox scripts). Cron it weekly to refresh.

set -euo pipefail
DEST="${WHEELHOUSE_DEST:-/opt/wheelhouse}"
mkdir -p "$DEST"

# Curated: what generated projects actually import day-to-day.
# NEVER include anything from the gate's blocklist.
PACKAGES=(
  fastapi uvicorn pydantic requests httpx aiohttp
  flask flask-cors
  python-telegram-bot discord.py
  apscheduler python-crontab
  sqlalchemy psycopg2-binary alembic
  beautifulsoup4 lxml
  pandas openpyxl
  python-dotenv pyyaml
  jinja2 markdown
  pillow qrcode
  pyjwt cryptography
  slowapi
)

echo "→ downloading wheels to $DEST ..."
pip3 download --dest "$DEST" --only-binary=:all: --python-version 3.13 "${PACKAGES[@]}" || \
  pip3 download --dest "$DEST" "${PACKAGES[@]}"   # fallback: sdists where no wheel exists

echo "✓ wheelhouse ready: $(ls "$DEST" | wc -l) files in $DEST"
echo "  set WHEELHOUSE_URL=$DEST in .env.postgres"
