#!/usr/bin/env python3
"""
Delete all projects via DELETE endpoint
Usage: python3 delete_all_projects.py [filter] [--yes]

Arguments:
  filter - Optional filter string (e.g., "test", "cryptoboard", "test-")
           Only projects with this string in their name will be deleted
           If not provided, ALL projects will be deleted (DANGEROUS!)
  --yes  - Skip confirmation and proceed with deletion immediately

Example:
  python3 delete_all_projects.py          # Delete ALL projects (interactive)
  python3 delete_all_projects.py test      # Delete only "test" projects (interactive)
  python3 delete_all_projects.py test --yes  # Delete without confirmation
"""

import sys
import json
import time
import sqlite3
from pathlib import Path
from datetime import datetime

# Backend API endpoint
API_BASE_URL = "http://localhost:8002"

def get_all_projects():
    """Get all projects from database"""
    db_path = Path("/root/clawd-backend/clawdbot_adapter.db")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, status, created_at, project_path
        FROM projects
        ORDER BY id DESC
    """)

    projects = cursor.fetchall()
    conn.close()

    return projects

def filter_projects(projects, filter_str):
    """Filter projects by name"""
    if not filter_str:
        return projects

    filter_str = filter_str.lower()
    return [p for p in projects if filter_str in p['name'].lower()]

def delete_project_via_api(project_id, project_name):
    """Delete project via DELETE endpoint"""
    import subprocess
    import json

    try:
        result = subprocess.run(
            ["curl", "-X", "DELETE",
             f"{API_BASE_URL}/projects/{project_id}",
             "-H", "Content-Type: application/json"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            response = json.loads(result.stdout)
            return True, response
        else:
            return False, result.stderr

    except subprocess.TimeoutExpired:
        return False, "Timeout after 30 seconds"
    except Exception as e:
        return False, str(e)

def confirm_delete(projects, filter_str=None):
    """Ask user for confirmation before deleting"""
    print("\n" + "=" * 80)
    print("PROJECTS TO DELETE")
    print("=" * 80)
    print(f"\nTotal: {len(projects)} projects\n")

    for p in projects:
        status_emoji = "✅" if p['status'] == 'ready' else "❌"
        print(f"  [{status_emoji}] ID {p['id']:3d} | {p['name']:40s} | {p['status']:10s}")

    if filter_str:
        print(f"\n📋 Filter: Only projects with '{filter_str}' in name")
    else:
        print("\n⚠️  WARNING: This will delete ALL projects!")

    print("\n" + "=" * 80)

    response = input("\nType 'DELETE' to confirm deletion: ").strip()

    return response == "DELETE"

def main():
    # Parse arguments
    filter_str = None
    skip_confirmation = False

    for arg in sys.argv[1:]:
        if arg == "--yes":
            skip_confirmation = True
            print("⚠️  Skipping confirmation (--yes flag set)")
        elif not arg.startswith("--"):
            filter_str = arg
            print(f"📋 Filter: Only deleting projects with '{filter_str}' in name")

    if not filter_str:
        print("⚠️  WARNING: No filter provided - will delete ALL projects!")

    # Get all projects
    print("\n📊 Fetching projects from database...")
    projects = get_all_projects()

    if not projects:
        print("✅ No projects found. Nothing to delete.")
        return

    # Apply filter
    if filter_str:
        filtered_projects = filter_projects(projects, filter_str)
        if not filtered_projects:
            print(f"✅ No projects found with filter '{filter_str}'. Nothing to delete.")
            return
        projects = filtered_projects

    # Confirm deletion (skip if --yes flag is set)
    if not skip_confirmation:
        if not confirm_delete(projects, filter_str):
            print("❌ Deletion cancelled.")
            return
    else:
        print("⚠️  Proceeding with deletion without confirmation...")

    # Delete projects one by one
    print("\n" + "=" * 80)
    print("STARTING DELETION")
    print("=" * 80)

    success_count = 0
    failed_count = 0
    skipped_count = 0

    start_time = datetime.now()

    for i, project in enumerate(projects, 1):
        project_id = project['id']
        project_name = project['name']
        project_status = project['status']
        project_path = project['project_path']

        print(f"\n[{i}/{len(projects)}] Deleting: {project_name} (ID: {project_id})")
        print(f"    Status: {project_status}")
        print(f"    Path: {project_path or 'N/A'}")

        # Skip failed projects (they likely don't have infrastructure)
        if project_status == 'failed' and not project_path:
            print("    ⏭️  Skipping (failed project with no path)")
            skipped_count += 1
            continue

        # Delete via API
        print(f"    🗑️  Calling DELETE endpoint...")
        success, result = delete_project_via_api(project_id, project_name)

        if success:
            print(f"    ✅ Success")
            success_count += 1

            # Show cleanup status if available
            if 'cleanup' in result:
                cleanup = result['cleanup']
                if cleanup and 'infrastructure' in cleanup:
                    infra = cleanup['infrastructure']
                    if isinstance(infra, dict):
                        steps = infra.get('steps', {})
                        if steps:
                            print(f"    📋 Cleanup steps:")
                            for step_name, step_result in steps.items():
                                if isinstance(step_result, dict):
                                    status = "✅" if 'error' not in step_result else "❌"
                                    print(f"        {status} {step_name}")
                                elif step_result == 'skipped':
                                    print(f"        ⏭️  {step_name} (skipped)")
        else:
            print(f"    ❌ Failed: {result}")
            failed_count += 1

        # Small delay between deletions
        if i < len(projects):
            time.sleep(1)

    # Summary
    end_time = datetime.now()
    duration = end_time - start_time

    print("\n" + "=" * 80)
    print("DELETION SUMMARY")
    print("=" * 80)
    print(f"\nTotal projects: {len(projects)}")
    print(f"✅ Successfully deleted: {success_count}")
    print(f"❌ Failed: {failed_count}")
    print(f"⏭️  Skipped: {skipped_count}")
    print(f"\n⏱️  Duration: {duration}")
    print(f"📊 Average time: {duration.total_seconds() / len(projects):.2f} seconds/project")

    if failed_count > 0:
        print(f"\n⚠️  Some projects failed to delete. Check the logs above.")
    elif skipped_count > 0:
        print(f"\nℹ️  Some projects were skipped (failed projects with no infrastructure).")
    else:
        print(f"\n🎉 All projects deleted successfully!")

if __name__ == "__main__":
    main()
