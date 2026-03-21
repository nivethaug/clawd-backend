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


# Shared virtual environment path (same as infrastructure_manager.py)
SHARED_VENV_PATH = "/root/dreampilot/dreampilotvenv"


def run(cmd: str, cwd: str = None, env: dict = None) -> bool:
    """Run shell command, return True if success"""
    print(f"\n▶ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, env=env)
    if result.returncode != 0:
        print(f"✗ Failed: {cmd}")
        return False
    print(f"✓ Success: {cmd}")
    return True


def install_dependencies(venv_path: str = None):
    """Install Python dependencies using shared venv with caching"""
    print("\n" + "="*50)
    print("PIP INSTALL")
    print("="*50)
    
    # Check for requirements.txt
    if not Path("requirements.txt").exists():
        print("⚠ No requirements.txt found, skipping")
        return True
    
    # Determine venv path
    venv = venv_path or SHARED_VENV_PATH
    pip_path = Path(venv) / "bin" / "pip"
    
    # Check if venv exists
    if pip_path.exists():
        print(f"📦 Using shared venv: {venv}")
        pip_cmd = str(pip_path)
    else:
        print("⚠ Shared venv not found, using system pip")
        pip_cmd = "pip"
    
    # Install with caching options (optimized flags)
    # --prefer-binary: Use binary wheels (faster, no compilation)
    # --no-cache-dir: Disable cache to avoid stale packages (optional)
    return run(f"{pip_cmd} install --prefer-binary -r requirements.txt")


def verify_main():
    """Verify main.py exists"""
    main_path = Path("main.py")
    if not main_path.exists():
        print("✗ main.py not found")
        return False
    print(f"✓ main.py verified: {main_path.stat().st_size} bytes")
    return True


def restart_pm2(domain: str = None):
    """Restart PM2 process
    
    Args:
        domain: Domain name (PM2 app name is {domain}-backend per infrastructure_manager.py)
                Uses {project_name} placeholder by default, replaced by infra manager
    """
    print("\n" + "="*50)
    print("PM2 RESTART")
    print("="*50)
    
    # Use placeholder if not provided (will be replaced by infra manager)
    if not domain:
        domain = "{project_name}"
    
    # PM2 app name convention: {domain}-backend (matches infrastructure_manager.py)
    app_name = f"{domain}-backend"
    print(f"📦 Restarting PM2 app: {app_name}")
    return run(f"pm2 restart {app_name}")


def reload_nginx():
    """Reload nginx configuration"""
    print("\n" + "="*50)
    print("NGINX RELOAD")
    print("="*50)
    return run("sudo nginx -s reload") or run("nginx -s reload")


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
    parser.add_argument("--domain", type=str, help="Domain for PM2 app name (e.g., learninggrid-tyh612 -> learninggrid-tyh612-backend)")
    parser.add_argument("--venv", type=str, help="Virtual environment path (default: /root/dreampilot/dreampilotvenv)")
    args = parser.parse_args()
    
    # Ensure we're in backend directory
    if not Path("main.py").exists():
        print("✗ Error: Run this script from the backend directory")
        sys.exit(1)
    
    success = True
    
    # Step 1: Install dependencies
    if not args.skip_deps:
        if not install_dependencies(args.venv):
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
        restart_pm2(args.domain)
        reload_nginx()
    

    
    print("\n" + "="*50)
    if success:
        print("✓ BUILD & PUBLISH COMPLETE")
    else:
        print("✗ BUILD FAILED")
    print("="*50)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
