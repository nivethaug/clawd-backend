#!/bin/bash
# Simple: Comment out Phase 8 call, update counts

echo "Step 1: Backup..."
cp openclaw_wrapper.py openclaw_wrapper.py.backup_simple

echo "Step 2: Comment out Phase 8 in run_all_phases..."
# Find the line with "if self.phase_8_frontend_ai_refinement():" and comment it out
sed -i 's/if self\.phase_8_frontend_ai_refinement():/# if self.phase_8_frontend_ai_refinement():/g' openclaw_wrapper.py

echo "Step 3: Update phase counts..."
sed -i 's/total_phases = 9/total_phases = 8/g' openclaw_wrapper.py

echo "Step 4: Update Phase X/9 to Phase X/8..."
for i in 1 2 3 4 5 6 7 8 9; do
    sed -i "s/Phase $i\/9/Phase $i\/8/g" openclaw_wrapper.py
done

echo "Step 5: Verify..."
python3 -m py_compile openclaw_wrapper.py 2>&1 && echo "✅ No syntax errors" || echo "❌ Syntax error found"

echo "Done!"
