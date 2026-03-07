#!/bin/bash
# Skip Phase 8, keep only Phase 9 as final phase

echo "=========================================="
echo "SKIP PHASE 8 - KEEP PHASE 9"
echo "=========================================="

echo ""
echo "Step 1: Backup..."
cp openclaw_wrapper.py openclaw_wrapper.py.backup_phase8

echo "✓ Backup created"

echo ""
echo "Step 2: Remove Phase 8 method (lines 476-605)..."
sed -i '476,605d' openclaw_wrapper.py

echo "✓ Phase 8 removed (130 lines)"

echo ""
echo "Step 3: Comment out Phase 8 call in run_all_phases()..."
# Find and comment out the Phase 8 call
sed -i 's/if self.phase_8_frontend_ai_refinement():/# Skipping Phase 8 - removed per request\n            # if self.phase_8_frontend_ai_refinement():/g' openclaw_wrapper.py

echo "✓ Phase 8 call commented out"

echo ""
echo "Step 4: Update phase counts (9 → 8)..."
sed -i 's/total_phases = 9/total_phases = 8/g' openclaw_wrapper.py

echo "✓ Total phases updated: 9 → 8"

echo ""
echo "Step 5: Update Phase numbers (Phase X/9 → Phase X/8)..."
sed -i 's/Phase 1\/9/Phase 1\/8/g' openclaw_wrapper.py
sed -i 's/Phase 2\/9/Phase 2\/8/g' openclaw_wrapper.py
sed -i 's/Phase 3\/9/Phase 3\/8/g' openclaw_wrapper.py
sed -i 's/Phase 4\/9/Phase 4\/8/g' openclaw_wrapper.py
sed -i 's/Phase 5\/9/Phase 5\/8/g' openclaw_wrapper.py
sed -i 's/Phase 6\/9/Phase 6\/8/g' openclaw_wrapper.py
sed -i 's/Phase 7\/9/Phase 7\/8/g' openclaw_wrapper.py
sed -i 's/Phase 8\/9/Phase 8\/8/g' openclaw_wrapper.py
sed -i 's/Phase 9\/9/Phase 9\/8/g' openclaw_wrapper.py

echo "✓ Phase numbers updated"

echo ""
echo "Step 6: Verify line count..."
new_lines=$(wc -l < openclaw_wrapper.py | awk '{print $1}')
old_lines=1055
removed_lines=130
expected_lines=$((old_lines - removed_lines))

echo "   Original: $old_lines lines"
echo "   Removed: $removed_lines lines"
echo "   Expected: $expected_lines lines"
echo "   Actual: $new_lines lines"

if [ $new_lines -eq $expected_lines ]; then
    echo "   ✓ Line count matches!"
else
    echo "   ⚠️ Line count mismatch: expected $expected_lines, got $new_lines"
fi

echo ""
echo "=========================================="
echo "✅ PHASE 8 SKIPPED!"
echo "=========================================="
echo ""
echo "Summary:"
echo "  ✓ Phase 8 method removed"
echo "  ✓ Phase 8 call commented out"
echo "  ✓ Total phases updated: 9 → 8"
echo "  ✓ Phase numbers updated: X/9 → X/8"
echo ""
echo "Result: 8 total phases (Phase 9 is now the final phase)"
echo ""
echo "Next steps:"
echo "  1. pm2 restart clawd-backend"
echo "  2. Create test project"
echo "  3. Verify 8 phases complete"
echo "  4. Check that Phase 9 (ACP) is working"
echo ""
