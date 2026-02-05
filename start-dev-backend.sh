#!/bin/bash
# Clawd Backend Development Startup Script

cd /root/clawd-backend

# Activate virtual environment
source venv/bin/activate

# Set correct database path (development can use the same or a separate DB)
export DB_PATH="/root/clawd-backend/clawdbot_adapter.db"

# Start the FastAPI application on port 8001 (development)
exec venv/bin/uvicorn app:app --host 0.0.0.0 --port 8001
