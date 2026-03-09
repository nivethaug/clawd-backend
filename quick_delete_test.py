#!/usr/bin/env python3
"""
Quick deletion of test projects - shows progress immediately
"""
import subprocess
import time
import sys

def get_test_projects():
    """Get test projects from PostgreSQL"""
    result = subprocess.run(
        ["docker", "exec", "dreampilot-postgres", "psql", "-U", "admin", "-d", "dreampilot",
         "-c", "SELECT id, name FROM projects WHERE name ILIKE '%test%' ORDER BY id"],
        capture_output=True, text=True, timeout=10
    )

    projects = []
    lines = result.stdout.strip().split('\n')
    for line in lines:
        if not line or line.startswith(('id', '-')):
            continue
        parts = line.split('|')
        if len(parts) >= 2:
            try:
                projects.append({'id': int(parts[0].strip()), 'name': parts[1].strip()})
            except:
                pass
    return projects

def delete_project(project_id, project_name):
    """Delete project via API"""
    result = subprocess.run(
        ["curl", "-s", "-X", "DELETE",
         f"http://localhost:8002/projects/{project_id}",
         "-H", "Content-Type: application/json"],
        capture_output=True, text=True, timeout=60
    )
    return result.returncode == 0

def main():
    print("🧪 Quick Test Project Deletion\n")

    # Get test projects
    print("📊 Fetching test projects...")
    projects = get_test_projects()

    if not projects:
        print("✅ No test projects found!")
        return

    print(f"Found {len(projects)} test projects\n")

    # Delete with progress
    start = time.time()
    success = 0
    failed = 0

    for i, p in enumerate(projects, 1):
        print(f"[{i}/{len(projects)}] Deleting ID {p['id']}: {p['name']}", end=' ', flush=True)

        if delete_project(p['id'], p['name']):
            print("✅")
            success += 1
        else:
            print("❌")
            failed += 1

        # Small delay
        time.sleep(0.5)

    # Summary
    duration = time.time() - start
    print(f"\n{'='*60}")
    print(f"Done in {duration:.1f}s ({duration/len(projects):.1f}s/project)")
    print(f"✅ Deleted: {success}")
    print(f"❌ Failed: {failed}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
