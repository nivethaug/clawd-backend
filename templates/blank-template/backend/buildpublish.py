#!/usr/bin/env python3
"""
Backend Build & Publish Script
Run from backend directory: python buildpublish.py [--skip-deps] [--restart] [--domain example-com]
"""

import subprocess
import sys
import os
import argparse
import re
from pathlib import Path


def run(cmd: str, cwd: str = None) -> bool:
    """Run shell command, return True if success"""
    print(f"\n▶ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if result.returncode != 0:
        print(f"✗ Failed: {cmd}")
        return False
    print(f"✓ Success: {cmd}")
    return True


def install_dependencies():
    """Install Python dependencies"""
    print("\n" + "="*50)
    print("PIP INSTALL")
    print("="*50)
    
    # Check for requirements.txt
    if not Path("requirements.txt").exists():
        print("⚠ No requirements.txt found, skipping")
        return True
    
    return run("pip install -r requirements.txt")


def verify_main():
    """Verify main.py exists"""
    main_path = Path("main.py")
    if not main_path.exists():
        print("✗ main.py not found")
        return False
    print(f"✓ main.py verified: {main_path.stat().st_size} bytes")
    return True


def restart_pm2(project_name: str = None):
    """Restart PM2 process"""
    print("\n" + "="*50)
    print("PM2 RESTART")
    print("="*50)
    
    if project_name:
        return run(f"pm2 restart {project_name}-backend")
    else:
        return run("pm2 restart all")


def reload_nginx():
    """Reload nginx configuration"""
    print("\n" + "="*50)
    print("NGINX RELOAD")
    print("="*50)
    return run("sudo nginx -s reload") or run("nginx -s reload")


def update_agent_readme(domain: str):
    """Replace {domain} placeholder in agent/README.md with actual domain"""
    print("\n" + "="*50)
    print("UPDATE AGENT README")
    print("="*50)
    
    readme_path = Path("agent/README.md")
    if not readme_path.exists():
        print("⚠ agent/README.md not found, skipping")
        return True
    
    try:
        content = readme_path.read_text(encoding="utf-8")
        
        # Replace {domain} placeholder
        if "{domain}" in content:
            content = content.replace("{domain}", domain)
            readme_path.write_text(content, encoding="utf-8")
            print(f"✓ Replaced {{domain}} → {domain} in agent/README.md")
        else:
            print("⚠ No {domain} placeholder found in agent/README.md")
        
        return True
    except Exception as e:
        print(f"✗ Failed to update agent/README.md: {e}")
        return False


def run_migrations():
    """Run database migrations if alembic is configured"""
    print("\n" + "="*50)
    print("DATABASE MIGRATIONS")
    print("="*50)
    
    if Path("alembic.ini").exists():
        return run("alembic upgrade head")
    else:
        print("⚠ No alembic.ini found, skipping migrations")
        return True


def main():
    parser = argparse.ArgumentParser(description="Backend Build & Publish")
    parser.add_argument("--skip-deps", action="store_true", help="Skip pip install")
    parser.add_argument("--skip-migrations", action="store_true", help="Skip database migrations")
    parser.add_argument("--restart", action="store_true", help="Restart PM2 and nginx")
    parser.add_argument("--project-name", type=str, help="Project name for PM2")
    parser.add_argument("--domain", type=str, help="Domain for placeholder replacement (e.g., learninggrid-tyh612)")
    args = parser.parse_args()
    
    # Ensure we're in backend directory
    if not Path("main.py").exists():
        print("✗ Error: Run this script from the backend directory")
        sys.exit(1)
    
    success = True
    
    # Step 1: Install dependencies
    if not args.skip_deps:
        if not install_dependencies():
            success = False
    
    # Step 2: Verify main.py
    if success:
        if not verify_main():
            success = False
    
    # Step 3: Run migrations (optional)
    if not args.skip_migrations and success:
        if not run_migrations():
            print("⚠ Migrations failed, continuing anyway")
    
    # Step 4: Restart services (optional)
    if args.restart and success:
        restart_pm2(args.project_name)
        reload_nginx()
    
    # Step 5: Update agent README with actual domain (if provided)
    if args.domain and success:
        update_agent_readme(args.domain)
    
    print("\n" + "="*50)
    if success:
        print("✓ BUILD & PUBLISH COMPLETE")
    else:
        print("✗ BUILD FAILED")
    print("="*50)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
