#!/usr/bin/env python3
"""
Frontend Build & Publish Script
Run from frontend directory: python buildpublish.py [--skip-install] [--skip-build] [--no-restart]

IMPORTANT: Call this script AFTER making ANY changes to the frontend code!
- If you modified any files in frontend/, run: python3 buildpublish.py
- This will rebuild the app and restart PM2 + nginx automatically
- Only skip restart with --no-restart if you're just testing locally

Matches infrastructure_manager.py build_frontend() process:
1. Clean Vite caches
2. Remove existing node_modules
3. npm ci (with NODE_ENV=development for devDependencies)
4. Remove old dist
5. npm run build
6. Verify dist
7. Fix permissions
8. Restart PM2 + nginx
9. Cleanup node_modules
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


def get_env_override():
    """Return environment with NODE_ENV=development to ensure devDependencies are installed.

    Servers may have NODE_ENV=production set globally, which causes npm to skip
    devDependencies like vite, vitest, @vitejs/plugin-react, @vitejs/plugin-react-swc.
    Forcing development guarantees a full install and correct build behaviour.
    """
    env = os.environ.copy()
    env["NODE_ENV"] = "development"
    return env


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


def npm_install(cwd: str = None):
    """Install npm dependencies via npm ci (matches infrastructure_manager.py)

    Uses NODE_ENV=development via get_env_override() so that devDependencies
    such as vite, vitest, @vitejs/plugin-react, and @vitejs/plugin-react-swc
    are always installed regardless of the server's global NODE_ENV.
    """
    print("\n" + "="*50)
    print("NPM CI")
    print("="*50)
    
    result = subprocess.run(
        [
            "npm",
            "ci",
            "--prefer-offline",
            "--no-audit",
            "--progress=false",
            "--legacy-peer-deps",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=cwd,
        env=get_env_override(),
    )
    
    if result.returncode != 0:
        # Extract actual errors from stderr (npm warnings go to stderr but don't fail)
        stderr_lines = result.stderr.split('\n')
        error_lines = [line for line in stderr_lines if any(kw in line.lower() for kw in ['error', 'err!', 'econnrefused', 'eacces', 'enoent'])]
        
        print(f"✗ npm ci failed with code {result.returncode}")
        if error_lines:
            print("Errors:")
            for line in error_lines[-10:]:
                print(f"  {line}")
        else:
            print(f"stderr: {result.stderr[:500]}")
        return False
    
    print("✓ npm ci completed")
    return True


def npm_build(cwd: str = None):
    """Build production bundle"""
    print("\n" + "="*50)
    print("NPM RUN BUILD")
    print("="*50)
    
    result = subprocess.run(
        ["npm", "run", "build"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=cwd,
        env=get_env_override(),
    )
    
    if result.returncode != 0:
        print("✗ npm run build failed")
        print("STDOUT:")
        print(result.stdout[-5000:])
        print("STDERR:")
        print(result.stderr[-5000:])
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
    """Restart the PM2 frontend process.

    Tries three strategies in order:
      1. Call worker-api's internal /internal/pm2-restart endpoint
         (works inside containers/sandbox where PM2 isn't directly accessible)
      2. Direct `pm2 restart` (host path, no sudo)
      3. `sudo pm2 restart` (last resort — fails in sandbox/container)

    Args:
        project_name: Domain (PM2 app name is {domain}-frontend)
    """
    print("\n" + "="*50)
    print("PM2 RESTART")
    print("="*50)

    # Use placeholder if not provided (will be replaced by infra manager)
    if not project_name:
        project_name = "{project_name}"

    app_name = f"{project_name}-frontend"
    print(f"📦 Restarting PM2 app: {app_name}")

    # Strategy 1: worker-api internal endpoint (container/sandbox path).
    worker_api_url = os.environ.get("DREAMPILOT_WORKER_API_URL")
    if worker_api_url:
        import json as _json
        import urllib.request as _urlreq
        endpoint = f"{worker_api_url}/internal/pm2-restart"
        payload = _json.dumps({"pm2_app_name": app_name}).encode()
        print(f"→ Calling worker-api: POST {endpoint}")
        try:
            req = _urlreq.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with _urlreq.urlopen(req, timeout=60) as resp:
                result = _json.loads(resp.read().decode())
            if result.get("success"):
                print(f"✓ Worker-api restarted PM2 app '{app_name}'")
                return True
            else:
                print(f"✗ Worker-api restart failed: {result.get('error', 'unknown')}")
        except Exception as e:
            print(f"⚠ Worker-api call failed: {e} — falling back to direct pm2")
    else:
        print("ℹ DREAMPILOT_WORKER_API_URL not set — skipping worker-api path")

    # Strategy 2: direct pm2 restart (host path, no sudo)
    if run(f"pm2 restart {app_name} --update-env"):
        return True

    # Strategy 3: sudo pm2 restart (last resort)
    print("⚠ bare pm2 restart failed, trying with sudo (may fail in sandbox/container)")
    return run(f"sudo pm2 restart {app_name}")


def reload_nginx():
    """Reload nginx configuration"""
    print("\n" + "="*50)
    print("NGINX RELOAD")
    print("="*50)
    if run("nginx -s reload"):
        return True
    return run("sudo nginx -s reload")

def remove_old_dist():
    """Remove existing dist directory before a fresh build.

    If dist exists, attempts to chown it to dreampilot:dreampilot first (fixes
    permission issues from previous root-owned builds) and then deletes it.
    Does nothing if dist does not exist.
    """
    print("\n" + "="*50)
    print("REMOVE OLD DIST")
    print("="*50)

    dist_path = Path("dist")

    if not dist_path.exists():
        print("⚠ dist not found, nothing to remove")
        return True

    try:
        subprocess.run(
            ["sudo", "chown", "-R", "dreampilot:dreampilot", "dist"],
            check=False,
            capture_output=True,
            text=True,
        )
        print("✓ Fixed dist ownership to dreampilot:dreampilot")
    except Exception as e:
        print(f"⚠ Ownership fix failed: {e}")

    try:
        shutil.rmtree(dist_path, ignore_errors=True)
        print("✓ Removed old dist")
    except Exception as e:
        print(f"⚠ Could not remove dist: {e}")
        return False

    return True

def main():
    parser = argparse.ArgumentParser(description="Frontend Build & Publish")
    parser.add_argument("--path", type=str, help="Frontend directory path (default: current directory)")
    parser.add_argument("--skip-install", action="store_true", help="Skip npm install")
    parser.add_argument("--skip-build", action="store_true", help="Skip npm build")
    parser.add_argument("--install-only", action="store_true", help="Run only npm ci (skip build, restart, cleanup)")
    parser.add_argument("--no-restart", action="store_true", help="Skip PM2 and nginx restart (restart is default)")
    args = parser.parse_args()
    
    # Determine frontend directory
    frontend_dir = Path(args.path) if args.path else Path.cwd()
    
    # Ensure we're in frontend directory (or --path points to frontend)
    if not (frontend_dir / "package.json").exists():
        print(f"✗ Error: package.json not found in {frontend_dir}")
        print("   Run from frontend directory or use --path <frontend-dir>")
        sys.exit(1)
    
    # Change to frontend directory for all operations
    os.chdir(frontend_dir)
    print(f"Working directory: {frontend_dir}")
    
    success = True
    
    # --install-only mode: Run only npm ci and exit
    if args.install_only:
        print("\n" + "="*50)
        print("INSTALL-ONLY MODE")
        print("="*50)
        
        clean_vite_caches()
        # Skip remove_node_modules - run npm ci on top of existing node_modules
        
        if npm_install(cwd=str(frontend_dir)):
            print("\n" + "="*50)
            print("✓ INSTALL-ONLY COMPLETE")
            print("="*50)
            sys.exit(0)
        else:
            print("\n" + "="*50)
            print("✗ INSTALL FAILED")
            print("="*50)
            sys.exit(1)
    
    # Step 1: Clean Vite caches
    clean_vite_caches()
    
    # Step 2: Remove existing node_modules for clean install
    if not args.skip_install:
        remove_node_modules()
    
    # Step 3: npm ci (with NODE_ENV=development for devDependencies)
    if not args.skip_install:
        if not npm_install(cwd=str(frontend_dir)):
            success = False

    # Step 4: Remove old dist (ONLY when a new build is about to run)
    if success and not args.skip_build:
        remove_old_dist()

    # Step 5: npm run build (with NODE_ENV=development)
    if not args.skip_build and success:
        if not npm_build(cwd=str(frontend_dir)):
            success = False
    
    # Step 6: Verify build
    if not args.skip_build and success:
        if not verify_dist():
            success = False
    
    # Step 7: Fix permissions
    if success:
        fix_permissions()
    
    # Step 8: Restart PM2 + nginx (MANDATORY by default)
    if not args.no_restart and success:
        restart_pm2()  # Uses {project_name} placeholder
        reload_nginx()

    # Step 9: Cleanup node_modules (after restart so nothing is needed anymore)
    if success:
        cleanup_node_modules()
    
    print("\n" + "="*50)
    if success:
        print("✓ BUILD & PUBLISH COMPLETE")
    else:
        print("✗ BUILD FAILED")
    print("="*50)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
