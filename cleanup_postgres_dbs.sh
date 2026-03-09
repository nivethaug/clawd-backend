#!/bin/bash
# Delete all PostgreSQL test databases (except system databases)

echo "🧹 DELETING ALL POSTGRESQL TEST DATABASES\n"
echo "⚠️  This will remove ~770 test databases and their users\n"

# List of protected databases (never delete these)
PROTECTED="postgres|template0|template1|dreampilot|defaultdb"

# Count databases
TOTAL=$(docker exec dreampilot-postgres psql -U admin -d postgres -t -c "\l" | grep -v "postgres\|template0\|template1\|dreampilot\|defaultdb" | wc -l)
echo "📊 Found $TOTAL test databases to delete\n"

# Counter
DELETED=0
FAILED=0

# Get all databases
DATABASES=$(docker exec dreampilot-postgres psql -U admin -d postgres -t -c "\l" | grep -v "postgres\|template0\|template1\|dreampilot\|defaultdb")

for db in $DATABASES; do
  # Skip protected databases
  if echo "$db" | grep -qE "^($PROTECTED)$"; then
    continue
  fi

  # Extract database name (remove _db suffix)
  db_name=$(echo "$db" | sed 's/_db$//')

  # Drop database
  echo "[$(date +%H:%M:%S)] Dropping database: $db"

  # Drop user first
  docker exec dreampilot-postgres psql -U admin -d postgres -c "DROP USER IF EXISTS \"$db_name_user\";" 2>/dev/null

  # Drop database
  result=$(docker exec dreampilot-postgres psql -U admin -d postgres -c "DROP DATABASE IF EXISTS \"$db\";" 2>&1)

  if echo "$result" | grep -q "ERROR"; then
    echo "  ❌ Failed: ${result:0:100}"
    FAILED=$((FAILED + 1))
  else
    echo "  ✅ Success"
    DELETED=$((DELETED + 1))
  fi

  # Small delay to avoid overwhelming the server
  sleep 0.1
done

echo -e "\n================================"
echo "🎉 CLEANUP COMPLETE"
echo "================================"
echo "✅ Databases deleted: $DELETED"
echo "❌ Failed: $FAILED"
echo -e "\n📊 Remaining databases:"
docker exec dreampilot-postgres psql -U admin -d postgres -c "\l" | grep -v "postgres\|template0\|template1\|dreampilot\|defaultdb" | wc -l
