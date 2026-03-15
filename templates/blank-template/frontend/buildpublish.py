#!/usr/bin/env python3
"""
Frontend Build & Publish Script
Run from frontend directory: python buildpublish.py [--skip-install] [--skip-build] [--restart]
"""

import subprocess
import sys
import os
import argparse
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


def npm_install():
    """Install npm dependencies"""
    print("\n" + "="*50)
    print("NPM INSTALL")
    print("="*50)
    return run("npm install")


def npm_build():
    """Build production bundle"""
    print("\n" + "="*50)
    print("NPM RUN BUILD")
    print("="*50)
    return run("npm run build")


def verify_dist():
    """Verify dist folder exists"""
    dist_path = Path("dist")
    if not dist_path.exists():
        print("✗ dist/ folder not found - build may have failed")
        return False
    index = dist_path / "index.html"
    if not index.exists():
        print("✗ dist/index.html not found")
        return False
    print(f"✓ Build verified: {index.stat().st_size} bytes")
    return True


def cleanup_node_modules():
    """Remove node_modules to save space"""
    print("\n" + "="*50)
    print("CLEANUP NODE_MODULES")
    print("="*50)
    
    node_modules = Path("node_modules")
    if not node_modules.exists():
        print("⚠ node_modules not found, skipping cleanup")
        return True
    
    # Get size before deletion
    total_size = sum(f.stat().st_size for f in node_modules.rglob("*") if f.is_file())
    size_mb = total_size / (1024 * 1024)
    
    if run("rm -rf node_modules"):
        print(f"✓ Freed {size_mb:.1f} MB")
        return True
    return False


def restart_pm2(project_name: str = None):
    """Restart PM2 process"""
    print("\n" + "="*50)
    print("PM2 RESTART")
    print("="*50)
    
    if project_name:
        return run(f"pm2 restart {project_name}-frontend")
    else:
        # Try to detect from package.json
        return run("pm2 restart all")


def reload_nginx():
    """Reload nginx configuration"""
    print("\n" + "="*50)
    print("NGINX RELOAD")
    print("="*50)
    return run("sudo nginx -s reload") or run("nginx -s reload")


def main():
    parser = argparse.ArgumentParser(description="Frontend Build & Publish")
    parser.add_argument("--skip-install", action="store_true", help="Skip npm install")
    parser.add_argument("--skip-build", action="store_true", help="Skip npm build")
    parser.add_argument("--restart", action="store_true", help="Restart PM2 and nginx")
    parser.add_argument("--project-name", type=str, help="Project name for PM2")
    args = parser.parse_args()
    
    # Ensure we're in frontend directory
    if not Path("package.json").exists():
        print("✗ Error: Run this script from the frontend directory")
        sys.exit(1)
    
    success = True
    
    # Step 1: npm install
    if not args.skip_install:
        if not npm_install():
            success = False
    
    # Step 2: npm run build
    if not args.skip_build and success:
        if not npm_build():
            success = False
    
    # Step 3: Verify build
    if not args.skip_build and success:
        if not verify_dist():
            success = False
    
    # Step 4: Cleanup node_modules (always after successful build)
    if success:
        cleanup_node_modules()
    
    # Step 5: Restart services (optional)
    if args.restart and success:
        restart_pm2(args.project_name)
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
