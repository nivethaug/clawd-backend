#!/usr/bin/env python3
"""
Delete all test projects via DELETE endpoint with PostgreSQL support
This script queries PostgreSQL and verifies infrastructure cleanup after each deletion.

Usage: python3 delete_test_projects.py [--yes]

Arguments:
  --yes  - Skip confirmation and proceed with deletion immediately
"""

import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime

# Backend API endpoint
API_BASE_URL = "http://localhost:8002"

def get_postgres_projects():
    """Get all projects from PostgreSQL database"""
    try:
        result = subprocess.run(
            ["docker", "exec", "dreampilot-postgres", "psql", "-U", "admin", "-d", "dreampilot",
             "-c", "SELECT id, name, project_path, status FROM projects ORDER BY id DESC"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            print(f"❌ Failed to query PostgreSQL: {result.stderr}")
            return []

        # Parse the output
        lines = result.stdout.strip().split('\n')
        projects = []

        # Skip header and separator lines
        for line in lines:
            line = line.strip()
            if not line or line.startswith("id") or line.startswith("-"):
                continue

            # Parse: id | name | project_path | status
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 4:
                projects.append({
                    'id': int(parts[0]),
                    'name': parts[1],
                    'project_path': parts[2],
                    'status': parts[3]
                })

        return projects

    except Exception as e:
        print(f"❌ Error getting PostgreSQL projects: {e}")
        return []

def filter_projects(projects, filter_str):
    """Filter projects by name"""
    filter_str = filter_str.lower()
    return [p for p in projects if filter_str in p['name'].lower()]

def verify_infrastructure(project_id, project_name, project_path):
    """Verify that infrastructure was cleaned up"""
    results = {
        'postgres': True,
        'folder': None,
        'pm2': None,
        'nginx': None
    }

    # 1. Check PostgreSQL record
    try:
        result = subprocess.run(
            ["docker", "exec", "dreampilot-postgres", "psql", "-U", "admin", "-d", "dreampilot",
             "-c", f"SELECT id FROM projects WHERE id = {project_id}"],
            capture_output=True,
            text=True,
            timeout=5
        )

        # Check if no rows returned (deleted successfully)
        output = result.stdout.strip()
        rows = [line for line in output.split('\n') if line.strip() and not line.startswith(('id', '-'))]

        if len(rows) == 0:
            results['postgres'] = True
        else:
            results['postgres'] = False
    except:
        results['postgres'] = False

    # 2. Check project folder
    if project_path and Path(project_path).exists():
        results['folder'] = False
    elif not project_path:
        results['folder'] = None  # No path to check
    else:
        results['folder'] = True

    # 3. Check PM2 services
    try:
        result = subprocess.run(
            ["pm2", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            pm2_data = json.loads(result.stdout)
            has_service = any(
                str(project_id) in proc.get('name', '') or
                project_name.lower().replace(' ', '-').replace('_', '-') in proc.get('name', '').lower()
                for proc in pm2_data
            )
            results['pm2'] = not has_service
    except:
        results['pm2'] = None

    # 4. Check nginx config
    try:
        result = subprocess.run(
            ["ls", "/etc/nginx/sites-enabled/"],
            capture_output=True,
            text=True,
            timeout=5
        )

        # Check if any config matches project name or ID
        config_files = result.stdout.lower()
        project_pattern = str(project_id) or project_name.lower().replace(' ', '-')
        has_config = any(
            project_pattern in config_file
            for config_file in config_files.split('\n')
        )

        results['nginx'] = not has_config
    except:
        results['nginx'] = None

    return results

def delete_project_via_api(project_id, project_name):
    """Delete project via DELETE endpoint"""
    try:
        result = subprocess.run(
            ["curl", "-X", "DELETE",
             f"{API_BASE_URL}/projects/{project_id}",
             "-H", "Content-Type: application/json"],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            response = json.loads(result.stdout)
            return True, response
        else:
            return False, result.stderr

    except subprocess.TimeoutExpired:
        return False, "Timeout after 60 seconds"
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
    skip_confirmation = False
    if "--yes" in sys.argv:
        skip_confirmation = True
        print("⚠️  Skipping confirmation (--yes flag set)")

    # Get all projects from PostgreSQL
    print("\n📊 Fetching projects from PostgreSQL...")
    projects = get_postgres_projects()

    if not projects:
        print("✅ No projects found in PostgreSQL. Nothing to delete.")
        return

    print(f"✅ Found {len(projects)} projects in PostgreSQL")

    # Filter for test projects
    test_projects = filter_projects(projects, "test")
    if not test_projects:
        print("✅ No test projects found. Nothing to delete.")
        return

    print(f"🧪 Found {len(test_projects)} test projects")

    # Confirm deletion
    if not skip_confirmation:
        if not confirm_delete(test_projects, "test"):
            print("❌ Deletion cancelled.")
            return
    else:
        print("⚠️  Proceeding with deletion without confirmation...")

    # Delete projects one by one
    print("\n" + "=" * 80)
    print("STARTING DELETION WITH INFRASTRUCTURE VERIFICATION")
    print("=" * 80)

    success_count = 0
    failed_count = 0
    skipped_count = 0
    cleanup_failures = []

    start_time = datetime.now()

    for i, project in enumerate(test_projects, 1):
        project_id = project['id']
        project_name = project['name']
        project_status = project['status']
        project_path = project['project_path']

        print(f"\n[{i}/{len(test_projects)}] Deleting: {project_name} (ID: {project_id})")
        print(f"    Status: {project_status}")
        print(f"    Path: {project_path or 'N/A'}")

        # Delete via API
        print(f"    🗑️  Calling DELETE endpoint...")
        success, result = delete_project_via_api(project_id, project_name)

        if not success:
            print(f"    ❌ Delete failed: {result}")
            failed_count += 1
            continue

        success_count += 1

        # Verify infrastructure cleanup
        print(f"    🔍 Verifying infrastructure cleanup...")
        time.sleep(1)  # Wait for cleanup to complete
        verification = verify_infrastructure(project_id, project_name, project_path)

        # Print verification results
        if verification['postgres']:
            print(f"        ✅ PostgreSQL record deleted")
        else:
            print(f"        ❌ PostgreSQL record still exists")
            cleanup_failures.append(f"{project_name}: PostgreSQL not deleted")

        if verification['folder'] is True:
            print(f"        ✅ Project folder deleted")
        elif verification['folder'] is False:
            print(f"        ❌ Project folder still exists")
            cleanup_failures.append(f"{project_name}: Folder not deleted")

        if verification['pm2'] is True:
            print(f"        ✅ PM2 services stopped")
        elif verification['pm2'] is False:
            print(f"        ❌ PM2 services still running")
            cleanup_failures.append(f"{project_name}: PM2 not stopped")
        elif verification['pm2'] is None:
            print(f"        ⏭️  PM2 check skipped")

        if verification['nginx'] is True:
            print(f"        ✅ Nginx config removed")
        elif verification['nginx'] is False:
            print(f"        ❌ Nginx config still exists")
            cleanup_failures.append(f"{project_name}: Nginx config not removed")
        elif verification['nginx'] is None:
            print(f"        ⏭️  Nginx check skipped")

    # Summary
    end_time = datetime.now()
    duration = end_time - start_time

    print("\n" + "=" * 80)
    print("DELETION SUMMARY")
    print("=" * 80)
    print(f"\nTotal projects: {len(test_projects)}")
    print(f"✅ Successfully deleted: {success_count}")
    print(f"❌ Failed: {failed_count}")
    print(f"⏭️  Skipped: {skipped_count}")
    print(f"\n⏱️  Duration: {duration}")
    print(f"📊 Average time: {duration.total_seconds() / len(test_projects):.2f} seconds/project")

    if cleanup_failures:
        print(f"\n⚠️  Infrastructure cleanup failures:")
        for failure in cleanup_failures:
            print(f"    - {failure}")
    elif failed_count > 0:
        print(f"\n⚠️  Some projects failed to delete. Check the logs above.")
    else:
        print(f"\n🎉 All test projects deleted successfully!")
        print(f"✅ All infrastructure verified and cleaned up!")

if __name__ == "__main__":
    main()
