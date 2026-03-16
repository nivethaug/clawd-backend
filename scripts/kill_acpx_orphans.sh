#!/bin/bash
# Kill orphaned ACPX processes
# Usage: ./kill_acpx_orphans.sh

echo "🔍 Searching for orphaned ACPX processes..."

# Find all claude-agent-acp processes
PIDS=$(pgrep -f "claude-agent-acp")

if [ -z "$PIDS" ]; then
    echo "✅ No orphaned ACPX processes found"
    exit 0
fi

echo "⚠️  Found orphaned ACPX processes:"
echo "$PIDS" | while read PID; do
    # Show process details
    ps -p "$PID" -o pid,ppid,cmd --no-headers
done

echo ""
echo "🔪 Killing processes..."

# Kill each process and its children
echo "$PIDS" | while read PID; do
    echo "Killing PID $PID and children..."
    
    # Get child PIDs
    CHILD_PIDS=$(pgrep -P "$PID")
    
    # Kill children first
    if [ -n "$CHILD_PIDS" ]; then
        echo "  Children: $CHILD_PIDS"
        echo "$CHILD_PIDS" | xargs kill -9 2>/dev/null
    fi
    
    # Kill main process
    kill -9 "$PID" 2>/dev/null
    
    # Kill process group (if exists)
    kill -9 -"$PID" 2>/dev/null
    
    echo "  ✓ Killed PID $PID"
done

# Verify all are dead
sleep 1
REMAINING=$(pgrep -f "claude-agent-acp")

if [ -z "$REMAINING" ]; then
    echo "✅ All orphaned ACPX processes killed successfully"
else
    echo "❌ Some processes still alive: $REMAINING"
    echo "Manual cleanup required: kill -9 $REMAINING"
    exit 1
fi
