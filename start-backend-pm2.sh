#!/bin/bash
# PM2 startup script for clawd-backend with venv activation

cd /root/clawd-backend
source venv/bin/activate
exec python3 -m uvicorn app:app --host 0.0.0.0 --port 8002
