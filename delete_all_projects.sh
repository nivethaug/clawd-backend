#!/bin/bash
# Delete ALL remaining projects

echo "🗑️  Deleting ALL remaining projects...\n"

# All remaining project IDs
for pid in 391 396 397 398 405 407 408 428 434; do
  echo "[$(date +%H:%M:%S)] Deleting ID $pid..."

  result=$(curl -X DELETE "http://localhost:8002/projects/$pid" \
    -H "Content-Type: application/json" \
    --max-time 120 -s)

  if echo "$result" | grep -q "deleted"; then
    echo "  ✅ Success"
  else
    echo "  ❌ Failed: ${result:0:100}"
  fi

  sleep 1
done

echo "\n✅ Done! Verifying..."
sleep 2

count=$(docker exec dreampilot-postgres psql -U admin -d dreampilot -t -c "SELECT COUNT(*) FROM projects;")
echo "📊 Projects remaining: $count"

if [ "$count" -eq "0" ]; then
  echo "🎉 ALL PROJECTS DELETED SUCCESSFULLY!"
else
  echo "⚠️  Some projects failed to delete"
fi
