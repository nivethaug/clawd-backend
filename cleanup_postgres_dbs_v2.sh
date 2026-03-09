#!/bin/bash
# Delete all PostgreSQL test databases (except system databases)

echo "🧹 DELETING ALL POSTGRESQL TEST DATABASES\n"

# Protected databases (never delete these)
PROTECTED="postgres|template0|template1|dreampilot|defaultdb|mywebapp"

# Get all database names (first column only)
echo "📊 Fetching database list..."
DATABASES=$(docker exec dreampilot-postgres psql -U admin -d postgres -t -A -F'|' -c "\l" | awk -F'|' '{print $1}')

# Count databases (excluding protected)
TOTAL=0
for db in $DATABASES; do
  if ! echo "$db" | grep -qE "^($PROTECTED)$"; then
    TOTAL=$((TOTAL + 1))
  fi
done

echo "Found $TOTAL test databases to delete\n"

# Counter
DELETED=0
FAILED=0

# Delete each database
for db in $DATABASES; do
  # Skip protected databases
  if echo "$db" | grep -qE "^($PROTECTED)$"; then
    continue
  fi

  # Extract base name (remove _db suffix)
  base_name=$(echo "$db" | sed 's/_db$//')

  echo "[$(date +%H:%M:%S)] Dropping: $db"

  # Drop user first
  docker exec dreampilot-postgres psql -U admin -d postgres -c "DROP USER IF EXISTS \"$base_name_user\";" 2>/dev/null

  # Drop database
  result=$(docker exec dreampilot-postgres psql -U admin -d postgres -c "DROP DATABASE IF EXISTS \"$db\";" 2>&1)

  if echo "$result" | grep -qi "error"; then
    echo "  ❌ Failed: ${result:0:80}"
    FAILED=$((FAILED + 1))
  else
    echo "  ✅ Success"
    DELETED=$((DELETED + 1))
  fi

  # Small delay
  sleep 0.1
done

echo -e "\n================================"
echo "🎉 CLEANUP COMPLETE"
echo "================================"
echo "✅ Databases deleted: $DELETED"
echo "❌ Failed: $FAILED"
echo -e "\n📊 Remaining databases (excluding system):"
REMAINING=$(docker exec dreampilot-postgres psql -U admin -d postgres -t -A -F'|' -c "\l" | awk -F'|' '{print $1}' | grep -vE "^($PROTECTED)$" | wc -l)
echo "$REMAINING databases"
