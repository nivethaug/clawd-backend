#!/usr/bin/env python3
"""
Fast parallel deletion of test projects
"""
import subprocess
import concurrent.futures
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

def delete_project(project):
    """Delete single project"""
    project_id, project_name = project['id'], project['name']
    result = subprocess.run(
        ["curl", "-s", "-X", "DELETE",
         f"http://localhost:8002/projects/{project_id}",
         "-H", "Content-Type: application/json"],
        capture_output=True, text=True, timeout=30
    )
    success = result.returncode == 0
    return project_id, project_name, success

def main():
    print("⚡ FAST PARALLEL TEST PROJECT DELETION\n")

    # Get test projects
    print("📊 Fetching test projects...")
    projects = get_test_projects()

    if not projects:
        print("✅ No test projects found!")
        return

    print(f"Found {len(projects)} test projects")
    print(f"Deleting in parallel (5 concurrent)...\n")

    # Delete in parallel batches of 5
    start = time.time()
    success_count = 0
    failed_count = 0
    failed_projects = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Submit all deletions
        future_to_project = {
            executor.submit(delete_project, p): p
            for p in projects
        }

        # Track progress
        total = len(projects)
        completed = 0

        # Process as they complete
        for future in concurrent.futures.as_completed(future_to_project):
            project = future_to_project[future]
            completed += 1

            try:
                project_id, project_name, success = future.result()
                status = "✅" if success else "❌"
                print(f"[{completed}/{total}] ID {project_id}: {project_name[:50]} {status}")

                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    failed_projects.append((project_id, project_name))

            except Exception as e:
                failed_count += 1
                print(f"[{completed}/{total}] ERROR: {project['name'][:50]} ❌ ({e})")

    # Summary
    duration = time.time() - start
    print(f"\n{'='*70}")
    print(f"Done in {duration:.1f}s ({duration/len(projects):.1f}s/project)")
    print(f"✅ Deleted: {success_count}")
    print(f"❌ Failed: {failed_count}")
    print(f"{'='*70}")

    if failed_projects:
        print(f"\nFailed projects:")
        for pid, name in failed_projects:
            print(f"  ID {pid}: {name}")

if __name__ == "__main__":
    main()
