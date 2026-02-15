#!/bin/bash
# Test the new openclaw agent command

set -e

API_BASE="http://localhost:8002"
PROJECT_NAME="test-agent-$(date +%s)"
DOMAIN="agent$(date +%s)"

echo "=========================================="
echo "Testing new openclaw agent command"
echo "=========================================="
echo ""

# Create a website project
echo "=== Creating website project ==="
CREATE_RESPONSE=$(curl -s -X POST "$API_BASE/projects" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"$PROJECT_NAME\",
    \"domain\": \"$DOMAIN\",
    \"description\": \"Test project for openclaw agent command\",
    \"typeId\": 1
  }")

echo "Create response:"
echo "$CREATE_RESPONSE" | python3 -m json.tool

# Extract project_id
PROJECT_ID=$(echo "$CREATE_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id'))")
echo ""
echo "✓ Project created with ID: $PROJECT_ID"

# Check initial status
echo ""
echo "=== Checking initial status ==="
STATUS_RESPONSE=$(curl -s -X GET "$API_BASE/projects/$PROJECT_ID/status")
echo "Status response:"
echo "$STATUS_RESPONSE" | python3 -m json.tool

echo ""
echo "=========================================="
echo "Background worker is now running..."
echo "Check status with: curl $API_BASE/projects/$PROJECT_ID/status"
echo "Watch logs with: pm2 logs clawd-backend | grep -E 'agent|worker|project $PROJECT_ID'"
echo "=========================================="
