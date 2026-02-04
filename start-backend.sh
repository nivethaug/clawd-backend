#!/bin/bash
# Clawd Backend Startup Script (FIXED)

cd /root/clawd-backend

# Activate virtual environment
source venv/bin/activate

# Set correct database path
export DB_PATH="/root/clawd-backend/clawdbot_adapter.db"

# Start the FastAPI application
exec venv/bin/uvicorn app:app --host 0.0.0.0 --port 8002
