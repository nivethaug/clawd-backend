#!/bin/bash
# Sequential deletion of remaining test projects

echo "🧪 Deleting remaining test projects sequentially..."

# List of remaining test project IDs
for pid in 402 403 404 406 409 410 411 412 413 414 415 416 417 418 419 420 421 422 423 424 425 426 427 429 430 432; do
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

echo "✅ Done!"
