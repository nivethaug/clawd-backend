#!/bin/bash

# Cleanup Script for Legacy Files
# Removes all backup, deprecated, and unused files from the codebase
# Date: 2026-03-14

set -e  # Exit on error

echo "========================================"
echo "DreamPilot Legacy Files Cleanup"
echo "========================================"
echo ""

# Create backup directory (safety measure)
BACKUP_DIR="legacy_files_backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
echo "✓ Created backup directory: $BACKUP_DIR"
echo ""

# List of files to remove
LEGACY_FILES=(
    # Backup files
    "acp_frontend_editor_v2_BACKUP.py"
    "app.py.backup"
    "chat_handlers.py.backup"
    "claude_code_worker.py.backup"
    
    # Old/deprecated files
    "database_postgres_old.py"
    "acp_frontend_editor.py"
    "NEW_phase8.py"
    "phase8_openclaw.py"
    "skip_phase8_keep_phase9.sh"
    "skip_phase8_simple.sh"
    "cleanup_old_projects.py"
    "simple_initializer.py"
    
    # Phase 8 backups
    "openclaw_wrapper.py.backup-phase8"
    "openclaw_wrapper.py.backup_phase8"
    "openclaw_wrapper.py.safe"
    "openclaw_wrapper.py.safe_integration"
    
    # Claude wrapper variants
    "claude_wrapper.py"
    "claude_wrapper_debug.py"
    "claude_wrapper_final.py"
    "claude_wrapper_simple.py"
    "claude_wrapper_step.py"
    
    # ACP editor variants
    "acp_frontend_editor_v2_FILESYSTEM_DIFF.py"
    "acp_frontend_editor_v2_FIXED.py"
    "acp_frontend_editor_v2_WRONG_METHOD.py.bak"
)

# Counter
removed_count=0
not_found_count=0
total_size=0

echo "Starting cleanup..."
echo ""

for file in "${LEGACY_FILES[@]}"; do
    if [ -f "$file" ]; then
        # Get file size
        size=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null || echo "0")
        total_size=$((total_size + size))
        
        # Move to backup first
        mv "$file" "$BACKUP_DIR/"
        
        echo "✓ Removed: $file ($(numfmt --to=iec $size 2>/dev/null || echo $size bytes))"
        ((removed_count++))
    else
        echo "⊘ Not found: $file"
        ((not_found_count++))
    fi
done

echo ""
echo "========================================"
echo "Cleanup Summary"
echo "========================================"
echo "Files removed: $removed_count"
echo "Files not found: $not_found_count"
echo "Total space freed: $(numfmt --to=iec $total_size 2>/dev/null || echo $total_size bytes)"
echo ""
echo "Backup location: $BACKUP_DIR/"
echo ""
echo "✅ Cleanup complete!"
echo ""
echo "To permanently delete backup (after verification):"
echo "  rm -rf $BACKUP_DIR"
echo ""
