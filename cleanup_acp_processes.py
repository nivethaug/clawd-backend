#!/usr/bin/env python3
"""
Manual cleanup script for orphaned claude-agent-acp processes.

Usage:
    python cleanup_acp_processes.py [--dry-run]

Options:
    --dry-run    Show what would be killed without actually killing
"""

import subprocess
import sys
import os
import signal


def find_acp_processes():
    """Find all claude-agent-acp processes."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "claude-agent-acp"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return []
        
        pids = [int(p.strip()) for p in result.stdout.strip().split('\n') if p.strip()]
        return pids
        
    except Exception as e:
        print(f"❌ Error finding processes: {e}")
        return []


def get_process_info(pid):
    """Get process command line info."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid,etime,cmd"],
            capture_output=True,
            text=True,
            timeout=2
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                return lines[1].strip()
        return f"PID {pid} (info unavailable)"
        
    except Exception:
        return f"PID {pid}"


def kill_process_tree(pid, dry_run=False):
    """Kill a process and all its children."""
    if dry_run:
        print(f"  [DRY-RUN] Would kill PID {pid}")
        return True
    
    try:
        # Get child processes
        result = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True,
            text=True,
            timeout=2
        )
        
        child_pids = []
        if result.returncode == 0:
            child_pids = [int(p.strip()) for p in result.stdout.strip().split('\n') if p.strip()]
        
        # Kill children first
        for child_pid in child_pids:
            try:
                os.kill(child_pid, signal.SIGKILL)
                print(f"  ✓ Killed child process {child_pid}")
            except (ProcessLookupError, OSError):
                pass
        
        # Kill main process
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"  ✓ Killed main process {pid}")
        except (ProcessLookupError, OSError):
            print(f"  ⚠ Process {pid} already dead")
        
        # Kill process group
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError, AttributeError):
            pass
        
        return True
        
    except Exception as e:
        print(f"  ❌ Failed to kill {pid}: {e}")
        return False


def main():
    """Main cleanup function."""
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    
    print("=" * 80)
    print("🧹 ACP Process Cleanup Tool")
    print("=" * 80)
    
    if dry_run:
        print("⚠️  DRY-RUN MODE - No processes will be killed")
        print()
    
    # Find processes
    print("🔍 Searching for claude-agent-acp processes...")
    pids = find_acp_processes()
    
    if not pids:
        print("✅ No orphaned ACP processes found!")
        print("=" * 80)
        return 0
    
    print(f"📋 Found {len(pids)} claude-agent-acp processes:")
    print()
    
    # Show process details
    for pid in pids:
        info = get_process_info(pid)
        print(f"  • {info}")
    
    print()
    print("-" * 80)
    
    # Confirm if not dry-run
    if not dry_run:
        print()
        response = input(f"⚠️  Kill {len(pids)} processes? [y/N]: ")
        
        if response.lower() not in ['y', 'yes']:
            print("❌ Cancelled")
            print("=" * 80)
            return 1
        
        print()
        print("🧹 Killing processes...")
    
    # Kill all processes
    killed_count = 0
    for pid in pids:
        if kill_process_tree(pid, dry_run=dry_run):
            killed_count += 1
    
    print()
    
    if dry_run:
        print(f"✅ Would kill {killed_count} processes (dry-run)")
    else:
        print(f"✅ Successfully killed {killed_count} processes")
    
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
