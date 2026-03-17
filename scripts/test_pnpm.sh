#!/bin/bash
# pnpm Diagnostic Script
# Run this on the server to diagnose pnpm issues

echo "=========================================="
echo "🔍 PNPM DIAGNOSTIC SCRIPT"
echo "=========================================="

echo ""
echo "1️⃣  Checking pnpm installation..."
which pnpm
pnpm --version

echo ""
echo "2️⃣  Checking node version..."
node --version
npm --version

echo ""
echo "3️⃣  Checking memory..."
free -h

echo ""
echo "4️⃣  Checking disk space..."
df -h /root

echo ""
echo "5️⃣  Checking ulimits..."
ulimit -a

echo ""
echo "6️⃣  Testing pnpm on a sample project..."
TEST_DIR="/tmp/pnpm-test-$$"
mkdir -p "$TEST_DIR"
cd "$TEST_DIR"

# Create minimal package.json
cat > package.json << 'EOF'
{
  "name": "pnpm-test",
  "version": "1.0.0",
  "dependencies": {
    "lodash": "^4.17.21"
  }
}
EOF

echo "   Created test project in $TEST_DIR"
echo "   Running: pnpm install --no-frozen-lockfile"
pnpm install --no-frozen-lockfile 2>&1
PNPM_EXIT=$?
echo "   Exit code: $PNPM_EXIT"

if [ $PNPM_EXIT -eq 0 ]; then
    echo "   ✅ pnpm works on minimal project"
else
    echo "   ❌ pnpm failed even on minimal project!"
fi

# Cleanup
cd /
rm -rf "$TEST_DIR"

echo ""
echo "7️⃣  Testing pnpm on actual frontend..."
# Find a frontend project
FRONTEND=$(find /root/dreampilot/projects -type d -name "frontend" 2>/dev/null | head -1)
if [ -n "$FRONTEND" ]; then
    echo "   Found: $FRONTEND"
    cd "$FRONTEND"
    
    # Remove lock files
    rm -f package-lock.json pnpm-lock.yaml
    
    echo "   Running: timeout 60 pnpm install 2>&1"
    timeout 60 pnpm install 2>&1
    echo "   Exit code: $?"
else
    echo "   No frontend project found"
fi

echo ""
echo "=========================================="
echo "🔍 DIAGNOSTIC COMPLETE"
echo "=========================================="
