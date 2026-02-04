#!/bin/bash
# Clawd Backend Development Startup Script
# Runs on port 8001 for feature branch testing

cd /root/clawd-backend

# Activate virtual environment
source venv/bin/activate

# Set correct database path
export DB_PATH="/root/clawd-backend/clawdbot_adapter.db"

# Start the FastAPI application on development port
exec venv/bin/uvicorn app:app --host 0.0.0.0 --port 8001
