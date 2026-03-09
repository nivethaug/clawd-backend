#!/usr/bin/env python3
import subprocess
import time

def get_all_databases():
    """Get list of all databases from PostgreSQL"""
    result = subprocess.run(
        ['docker', 'exec', 'dreampilot-postgres', 'psql', '-U', 'admin', '-d', 'postgres',
         '-c', '\\l'],
        capture_output=True,
        text=True,
        timeout=10
    )

    # Parse output - skip header lines
    databases = []
    lines = result.stdout.split('\n')

    for line in lines:
        # Skip header lines and system databases
        if not line or line.startswith(('Name', '-', 'postgres', 'template0', 'template1', 'dreampilot', 'defaultdb', 'mywebapp')):
            continue

        # Extract database name (first column)
        parts = line.split('|')
        if parts and len(parts) > 0:
            db_name = parts[0].strip()
            if db_name and db_name not in ['postgres', 'template0', 'template1', 'dreampilot', 'defaultdb', 'mywebapp']:
                databases.append(db_name)

    return databases

def drop_database(db_name):
    """Drop a database and its user"""
    # Extract base name (remove _db suffix)
    base_name = db_name.replace('_db', '')

    # Drop user
    user_result = subprocess.run(
        ['docker', 'exec', 'dreampilot-postgres', 'psql', '-U', 'admin', '-d', 'postgres',
         '-c', f'DROP USER IF EXISTS "{base_name}_user";'],
        capture_output=True,
        text=True,
        timeout=5
    )

    # Drop database
    db_result = subprocess.run(
        ['docker', 'exec', 'dreampilot-postgres', 'psql', '-U', 'admin', '-d', 'postgres',
         '-c', f'DROP DATABASE IF EXISTS "{db_name}";'],
        capture_output=True,
        text=True,
        timeout=10
    )

    return db_result.returncode == 0

def main():
    print("🧹 DELETING ALL POSTGRESQL TEST DATABASES\n")

    # Get all databases
    print("📊 Fetching database list...")
    databases = get_all_databases()

    if not databases:
        print("✅ No test databases found!")
        return

    print(f"Found {len(databases)} test databases to delete\n")

    # Delete databases
    deleted = 0
    failed = 0

    for i, db in enumerate(databases, 1):
        print(f"[{i}/{len(databases)}] Dropping: {db}")

        success = drop_database(db)

        if success:
            print(f"    ✅ Success")
            deleted += 1
        else:
            print(f"    ❌ Failed")
            failed += 1

        # Small delay
        time.sleep(0.1)

    # Summary
    print(f"\n{'='*60}")
    print("CLEANUP COMPLETE")
    print(f"{'='*60}")
    print(f"\n✅ Databases deleted: {deleted}")
    print(f"❌ Failed: {failed}")

if __name__ == '__main__':
    main()
