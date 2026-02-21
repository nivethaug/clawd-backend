#!/bin/bash
# Clawd Backend Startup Script
# Supports both SQLite and PostgreSQL modes

cd /root/clawd-backend

# Activate virtual environment
source venv/bin/activate

# Check for PostgreSQL configuration
POSTGRES_ENV_FILE="/root/clawd-backend/.env.postgres"

if [ -f "$POSTGRES_ENV_FILE" ]; then
    # Load PostgreSQL environment variables
    source "$POSTGRES_ENV_FILE"
    
    # Set PostgreSQL mode
    export USE_POSTGRES=true
    
    echo "Starting backend with PostgreSQL database..."
    echo "  Host: $DB_HOST"
    echo "  Port: $DB_PORT"
    echo "  Database: $DB_NAME"
    echo "  User: $DB_USER"
else
    # SQLite mode (fallback/default)
    export USE_POSTGRES=false
    export DB_PATH="/root/clawd-backend/clawdbot_adapter.db"
    
    echo "Starting backend with SQLite database..."
    echo "  Database: $DB_PATH"
fi

# Start the FastAPI application
exec venv/bin/uvicorn app:app --host 0.0.0.0 --port 8002
