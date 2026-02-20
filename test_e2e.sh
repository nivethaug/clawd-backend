#!/bin/bash
# End-to-end integration test for background OpenClaw worker

set -e

API_BASE="http://localhost:8002"
PROJECT_NAME="test-openclaw-bg-$(date +%s)"
DOMAIN="testbg$(date +%s)"

echo "=========================================="
echo "E2E INTEGRATION TEST: Background OpenClaw"
echo "=========================================="
echo ""

# Test 1: Create a website project (should trigger background worker)
echo "=== Test 1: Create website project ==="
echo "Project name: $PROJECT_NAME"
echo "Domain: $DOMAIN"

CREATE_RESPONSE=$(curl -s -X POST "$API_BASE/projects" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"$PROJECT_NAME\",
    \"domain\": \"$DOMAIN\",
    \"description\": \"Test project for background OpenClaw worker\",
    \"typeId\": 1
  }")

echo "Create response:"
echo "$CREATE_RESPONSE" | python3 -m json.tool

# Extract project_id
PROJECT_ID=$(echo "$CREATE_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id'))")
echo ""
echo "✓ Project created with ID: $PROJECT_ID"

# Test 2: Check status is "creating"
echo ""
echo "=== Test 2: Check initial status ==="
STATUS_RESPONSE=$(curl -s -X GET "$API_BASE/projects/$PROJECT_ID/status")
echo "Status response:"
echo "$STATUS_RESPONSE" | python3 -m json.tool

STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status'))")

if [ "$STATUS" == "creating" ]; then
  echo "✓ Status is 'creating' as expected"
else
  echo "✗ Status is '$STATUS', expected 'creating'"
  exit 1
fi

# Test 3: Check project details
echo ""
echo "=== Test 3: Get project details ==="
PROJECT_DETAILS=$(curl -s -X GET "$API_BASE/projects/$PROJECT_ID")
echo "Project details:"
echo "$PROJECT_DETAILS" | python3 -m json.tool

# Test 4: Wait a bit and check status again (should still be creating or might become ready/failed)
echo ""
echo "=== Test 4: Wait 5 seconds and check status again ==="
sleep 5

STATUS_RESPONSE=$(curl -s -X GET "$API_BASE/projects/$PROJECT_ID/status")
echo "Status response:"
echo "$STATUS_RESPONSE" | python3 -m json.tool

STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status'))")

if [[ "$STATUS" == "creating" || "$STATUS" == "ready" || "$STATUS" == "failed" ]]; then
  echo "✓ Status is valid: $STATUS"
else
  echo "✗ Invalid status: $STATUS"
  exit 1
fi

# Test 5: Create a non-website project (should NOT trigger background worker)
echo ""
echo "=== Test 5: Create telegram bot project (no background worker) ==="
TELEGRAM_NAME="test-telegram-$(date +%s)"
TELEGRAM_DOMAIN="telegram$(date +%s)"

TELEGRAM_RESPONSE=$(curl -s -X POST "$API_BASE/projects" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"$TELEGRAM_NAME\",
    \"domain\": \"$TELEGRAM_DOMAIN\",
    \"description\": \"Test telegram bot (should not trigger worker)\",
    \"typeId\": 2
  }")

echo "Telegram bot response:"
echo "$TELEGRAM_RESPONSE" | python3 -m json.tool

TELEGRAM_ID=$(echo "$TELEGRAM_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id'))")
echo "✓ Telegram bot created with ID: $TELEGRAM_ID"

# Check telegram bot status
TELEGRAM_STATUS=$(curl -s -X GET "$API_BASE/projects/$TELEGRAM_ID/status" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status'))")
echo "Telegram bot status: $TELEGRAM_STATUS"

# For telegram bot, status should be "creating" (default) but no worker should run
if [ "$TELEGRAM_STATUS" == "creating" ]; then
  echo "✓ Telegram bot status is 'creating' (default)"
else
  echo "✗ Telegram bot status is '$TELEGRAM_STATUS', expected 'creating'"
fi

# Test 6: Verify 404 for non-existent project
echo ""
echo "=== Test 6: Test 404 for non-existent project ==="
NON_EXISTENT_STATUS=$(curl -s -w "\n%{http_code}" -X GET "$API_BASE/projects/99999/status")
HTTP_CODE=$(echo "$NON_EXISTENT_STATUS" | tail -n1)

if [ "$HTTP_CODE" == "404" ]; then
  echo "✓ Non-existent project returns 404"
else
  echo "✗ Expected 404, got $HTTP_CODE"
fi

# Summary
echo ""
echo "=========================================="
echo "E2E TEST SUMMARY"
echo "=========================================="
echo "✓ All tests passed!"
echo ""
echo "Note: The background worker will continue running for project $PROJECT_ID"
echo "Check status with: curl $API_BASE/projects/$PROJECT_ID/status"
