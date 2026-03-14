# Cleanup Script for Legacy Files (PowerShell)
# Removes all backup, deprecated, and unused files from the codebase
# Date: 2026-03-14

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "DreamPilot Legacy Files Cleanup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Create backup directory (safety measure)
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "legacy_files_backup_$timestamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Write-Host "✓ Created backup directory: $backupDir" -ForegroundColor Green
Write-Host ""

# List of files to remove
$legacyFiles = @(
    # Backup files
    "acp_frontend_editor_v2_BACKUP.py",
    "app.py.backup",
    "chat_handlers.py.backup",
    "claude_code_worker.py.backup",
    
    # Old/deprecated files
    "database_postgres_old.py",
    "acp_frontend_editor.py",
    "NEW_phase8.py",
    "phase8_openclaw.py",
    "skip_phase8_keep_phase9.sh",
    "skip_phase8_simple.sh",
    "cleanup_old_projects.py",
    "simple_initializer.py",
    
    # Phase 8 backups
    "openclaw_wrapper.py.backup-phase8",
    "openclaw_wrapper.py.backup_phase8",
    "openclaw_wrapper.py.safe",
    "openclaw_wrapper.py.safe_integration",
    
    # Claude wrapper variants
    "claude_wrapper.py",
    "claude_wrapper_debug.py",
    "claude_wrapper_final.py",
    "claude_wrapper_simple.py",
    "claude_wrapper_step.py",
    
    # ACP editor variants
    "acp_frontend_editor_v2_FILESYSTEM_DIFF.py",
    "acp_frontend_editor_v2_FIXED.py",
    "acp_frontend_editor_v2_WRONG_METHOD.py.bak"
)

# Counter
$removedCount = 0
$notFoundCount = 0
$totalSize = 0

Write-Host "Starting cleanup..." -ForegroundColor Yellow
Write-Host ""

foreach ($file in $legacyFiles) {
    if (Test-Path $file) {
        # Get file size
        $fileInfo = Get-Item $file
        $size = $fileInfo.Length
        $totalSize += $size
        
        # Move to backup first
        Move-Item -Path $file -Destination $backupDir -Force
        
        $sizeFormatted = "{0:N2} KB" -f ($size / 1KB)
        Write-Host "✓ Removed: $file ($sizeFormatted)" -ForegroundColor Green
        $removedCount++
    }
    else {
        Write-Host "⊘ Not found: $file" -ForegroundColor DarkGray
        $notFoundCount++
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Cleanup Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Files removed: $removedCount" -ForegroundColor Yellow
Write-Host "Files not found: $notFoundCount" -ForegroundColor DarkGray

$totalSizeFormatted = "{0:N2} MB" -f ($totalSize / 1MB)
Write-Host "Total space freed: $totalSizeFormatted" -ForegroundColor Green
Write-Host ""
Write-Host "Backup location: $backupDir\" -ForegroundColor Cyan
Write-Host ""
Write-Host "✅ Cleanup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To permanently delete backup (after verification):" -ForegroundColor Yellow
Write-Host "  Remove-Item -Recurse -Force $backupDir" -ForegroundColor White
Write-Host ""
