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
    
    try:
        # Find all claude-agent-acp processes
        result = subprocess.run(
            ["pgrep", "-f", "claude-agent-acp"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            print("✅ No orphaned ACPX processes found")
            return 0
        
        pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
        
        if not pids:
            print("✅ No orphaned ACPX processes found")
            return 0
        
        print(f"🔍 Found {len(pids)} orphaned process(es): {', '.join(pids)}")
        
        # Kill them all with SIGKILL
        kill_result = subprocess.run(
            ["pkill", "-9", "-f", "claude-agent-acp"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if kill_result.returncode == 0:
            print(f"✅ Successfully killed {len(pids)} orphaned process(es)")
            return len(pids)
        else:
            print(f"⚠️  Failed to kill some processes (exit code {kill_result.returncode})")
            if kill_result.stderr:
                print(f"   Error: {kill_result.stderr}")
            return 0
            
    except subprocess.TimeoutExpired:
        print("❌ Timeout while searching for processes")
        return 0
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        return 0


if __name__ == "__main__":
    killed_count = cleanup_orphan_acpx_processes()
    sys.exit(0 if killed_count >= 0 else 1)
