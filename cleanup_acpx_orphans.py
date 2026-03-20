#!/usr/bin/env python3
"""
Cleanup script for orphaned ACPX processes.

Kills all claude-agent-acp processes that may have survived process tree kills.

Usage:
    python cleanup_acpx_orphans.py
"""

import subprocess
import sys


def cleanup_orphan_acpx_processes():
    """Kill all orphaned claude-agent-acp processes."""
    print("🧹 Cleaning up orphaned ACPX processes...")
    
    # NOTE: Process name gets truncated to 15 chars in /proc/[pid]/comm
    # so "claude-agent-acp" appears as "claude-agent-ac"
    patterns = ["claude-agent-ac", "_npx.*claude-agent"]
    
    total_killed = 0
    
    for pattern in patterns:
        try:
            # Find processes matching this pattern
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                continue
            
            pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
            
            if not pids:
                continue
            
            print(f"🔍 Found {len(pids)} process(es) matching '{pattern}': {', '.join(pids)}")
            
            # Kill them all with SIGKILL
            kill_result = subprocess.run(
                ["pkill", "-9", "-f", pattern],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if kill_result.returncode == 0:
                print(f"✅ Successfully killed {len(pids)} process(es) with pattern '{pattern}'")
                total_killed += len(pids)
            else:
                print(f"⚠️  Failed to kill some processes (exit code {kill_result.returncode})")
                if kill_result.stderr:
                    print(f"   Error: {kill_result.stderr}")
                    
        except subprocess.TimeoutExpired:
            print(f"❌ Timeout while searching for pattern '{pattern}'")
        except Exception as e:
            print(f"❌ Error with pattern '{pattern}': {e}")
    
    if total_killed == 0:
        print("✅ No orphaned ACPX processes found")
    
    return total_killed


if __name__ == "__main__":
    killed_count = cleanup_orphan_acpx_processes()
    sys.exit(0 if killed_count >= 0 else 1)
