#!/usr/bin/env python3
"""
Frontend Build & Publish Script
Run from frontend directory: python buildpublish.py [--skip-install] [--skip-build] [--restart]

Matches infrastructure_manager.py build_frontend() process:
1. Clean Vite caches
2. Remove existing node_modules
3. npm install --include=dev --legacy-peer-deps
4. npm run build
5. Verify dist
6. Fix permissions
7. Cleanup node_modules
"""

import subprocess
import sys
import os
import argparse
import shutil
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


def clean_vite_caches():
    """Clean Vite caches to prevent corrupted builds"""
    print("\n" + "="*50)
    print("CLEAN VITE CACHES")
    print("="*50)
    
    caches_cleaned = 0
    node_modules = Path("node_modules")
    
    vite_temp = node_modules / ".vite-temp"
    vite_cache = node_modules / ".vite"
    
    if vite_temp.exists():
        try:
            shutil.rmtree(vite_temp)
            print("✓ Cleaned .vite-temp")
            caches_cleaned += 1
        except Exception as e:
            print(f"⚠ Could not clean .vite-temp: {e}")
    
    if vite_cache.exists():
        try:
            shutil.rmtree(vite_cache)
            print("✓ Cleaned .vite cache")
            caches_cleaned += 1
        except Exception as e:
            print(f"⚠ Could not clean .vite: {e}")
    
    print(f"✓ Cleaned {caches_cleaned} cache directories")
    return True


def remove_node_modules():
    """Remove existing node_modules for clean install"""
    print("\n" + "="*50)
    print("REMOVE NODE_MODULES")
    print("="*50)
    
    node_modules = Path("node_modules")
    if node_modules.exists():
        try:
            shutil.rmtree(node_modules)
            print("✓ Removed existing node_modules")
        except Exception as e:
            print(f"⚠ Could not remove node_modules: {e}")
    else:
        print("⚠ node_modules not found, skipping")
    return True


def npm_install():
    """Install npm dependencies with legacy peer deps (dev deps install by default)"""
    print("\n" + "="*50)
    print("NPM INSTALL")
    print("="*50)
    
    # Match infrastructure_manager.py approach
    # Note: --include=dev is not universally supported, dev deps install by default
    # Use --prefer-offline to use npm cache when available
    result = subprocess.run(
        ["npm", "install", "--prefer-offline", "--legacy-peer-deps"],
        capture_output=True,
        text=True,
        timeout=600
    )
    
    if result.returncode != 0:
        # Extract actual errors from stderr (npm warnings go to stderr but don't fail)
        stderr_lines = result.stderr.split('\n')
        error_lines = [line for line in stderr_lines if any(kw in line.lower() for kw in ['error', 'err!', 'econnrefused', 'eacces', 'enoent'])]
        
        print(f"✗ npm install failed with code {result.returncode}")
        if error_lines:
            print("Errors:")
            for line in error_lines[-10:]:
                print(f"  {line}")
        else:
            print(f"stderr: {result.stderr[:500]}")
        return False
    
    print("✓ npm install completed (including dev dependencies)")
    return True


def npm_build():
    """Build production bundle"""
    print("\n" + "="*50)
    print("NPM RUN BUILD")
    print("="*50)
    
    result = subprocess.run(
        ["npm", "run", "build"],
        capture_output=True,
        text=True,
        timeout=600
    )
    
    if result.returncode != 0:
        print(f"✗ npm run build failed: {result.stderr[:500]}")
        return False
    
    print("✓ npm run build completed")
    return True


def verify_dist():
    """Verify dist folder exists and has content"""
    print("\n" + "="*50)
    print("VERIFY DIST")
    print("="*50)
    
    dist_path = Path("dist")
    if not dist_path.exists():
        print("✗ dist/ folder not found - build may have failed")
        return False
    
    index = dist_path / "index.html"
    if not index.exists():
        print("✗ dist/index.html not found")
        return False
    
    dist_contents = list(dist_path.iterdir())
    print(f"✓ Dist verified: {len(dist_contents)} items, index.html: {index.stat().st_size} bytes")
    return True


def fix_permissions():
    """Fix permissions for nginx access (755 dirs, 644 files)"""
    print("\n" + "="*50)
    print("FIX PERMISSIONS")
    print("="*50)
    
    dist_path = Path("dist")
    if not dist_path.exists():
        print("⚠ dist/ not found, skipping permissions")
        return True
    
    try:
        os.chmod(dist_path, 0o755)
        for item in dist_path.rglob("*"):
            if item.is_file():
                os.chmod(item, 0o644)
            elif item.is_dir():
                os.chmod(item, 0o755)
        print("✓ Permissions fixed (755/644)")
    except Exception as e:
        print(f"⚠ Could not fix permissions: {e}")
    
    return True


def cleanup_node_modules():
    """Remove node_modules to save space after build"""
    print("\n" + "="*50)
    print("CLEANUP NODE_MODULES")
    print("="*50)
    
    node_modules = Path("node_modules")
    if not node_modules.exists():
        print("⚠ node_modules not found, skipping cleanup")
        return True
    
    # Calculate size before deletion
    try:
        total_size = sum(f.stat().st_size for f in node_modules.rglob("*") if f.is_file())
        size_mb = total_size / (1024 * 1024)
    except:
        size_mb = 0
    
    try:
        shutil.rmtree(node_modules)
        print(f"✓ Removed node_modules (freed {size_mb:.1f} MB)")
    except Exception as e:
        print(f"⚠ Could not remove node_modules: {e}")
    
    return True


def restart_pm2(project_name: str = None):
    """Restart PM2 process"""
    print("\n" + "="*50)
    print("PM2 RESTART")
    print("="*50)
    
    if project_name:
        return run(f"pm2 restart {project_name}-frontend")
    else:
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
    
    # Step 1: Clean Vite caches
    clean_vite_caches()
    
    # Step 2: Remove existing node_modules for clean install
    if not args.skip_install:
        remove_node_modules()
    
    # Step 3: npm install
    if not args.skip_install:
        if not npm_install():
            success = False
    
    # Step 4: npm run build
    if not args.skip_build and success:
        if not npm_build():
            success = False
    
    # Step 5: Verify build
    if not args.skip_build and success:
        if not verify_dist():
            success = False
    
    # Step 6: Fix permissions
    if success:
        fix_permissions()
    
    # Step 7: Cleanup node_modules
    if success:
        cleanup_node_modules()
    
    # Step 8: Restart services (optional)
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
