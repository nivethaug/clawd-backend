#!/usr/bin/env python3
"""
Automatic project cleanup - delete projects older than 4 hours
"""

import requests
import sys
from datetime import datetime, timedelta

BACKEND_URL = "http://localhost:8002"
MAX_AGE_HOURS = 4

def cleanup_old_projects():
    """Delete projects older than MAX_AGE_HOURS"""

    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Starting cleanup of projects older than {MAX_AGE_HOURS} hours...")

    # Get all projects
    try:
        response = requests.get(f"{BACKEND_URL}/projects", timeout=30)
        projects = response.json()
    except Exception as e:
        print(f"❌ Failed to fetch projects: {e}")
        return 1

    if not projects:
        print("✅ No projects to check")
        return 0

    # Calculate cutoff time
    cutoff_time = datetime.utcnow() - timedelta(hours=MAX_AGE_HOURS)

    # Find old projects
    old_projects = []
    for project in projects:
        created_at = project.get('created_at')
        if not created_at:
            continue

        # Parse created_at timestamp
        try:
            created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if created_dt < cutoff_time:
                old_projects.append(project)
        except Exception as e:
            print(f"⚠️  Could not parse created_at for project {project['id']}: {e}")
            continue

    if not old_projects:
        print(f"✅ No projects older than {MAX_AGE_HOURS} hours")
        return 0

    print(f"Found {len(old_projects)} projects older than {MAX_AGE_HOURS} hours")
    print(f"Cutoff time: {cutoff_time.isoformat()}")

    # Delete old projects
    success = 0
    failed = 0

    for project in old_projects:
        project_id = project['id']
        project_name = project['name']
        created_at = project.get('created_at', 'Unknown')

        print(f"\n  Deleting {project_id}: {project_name}")
        print(f"    Created: {created_at}")

        try:
            response = requests.delete(f"{BACKEND_URL}/projects/{project_id}", timeout=30)
            if response.status_code in [200, 204, 404]:
                print(f"    ✅ Deleted")
                success += 1
            else:
                print(f"    ❌ Failed (HTTP {response.status_code})")
                failed += 1
        except Exception as e:
            print(f"    ❌ Error: {e}")
            failed += 1

        # Delay between deletions
        import time
        time.sleep(1)

    print(f"\n{'='*60}")
    print(f"Cleanup complete!")
    print(f"  Old projects found: {len(old_projects)}")
    print(f"  Deleted successfully: {success}")
    print(f"  Failed: {failed}")
    print(f"{'='*60}")

    return 0

if __name__ == "__main__":
    sys.exit(cleanup_old_projects())
