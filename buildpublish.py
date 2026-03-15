#!/usr/bin/env python3
"""
Build and Publish Script for DreamPilot Projects

Usage:
    python buildpublish.py --project <project_name> [--frontend] [--backend] [--restart-nginx]

Examples:
    python buildpublish.py --project myapp --frontend
    python buildpublish.py --project myapp --backend
    python buildpublish.py --project myapp --frontend --backend --restart-nginx
"""

import argparse
import subprocess
import sys
import os
import time
import logging
from pathlib import Path
from typing import Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Project paths
PROJECTS_BASE_PATH = Path("/root/dreampilot/projects/website")


class BuildPublisher:
    """Handles building and publishing for frontend and backend projects."""
    
    def __init__(self, project_name: str):
        self.project_name = project_name
        self.project_path = PROJECTS_BASE_PATH / project_name
        self.frontend_path = self.project_path / "frontend"
        self.backend_path = self.project_path / "backend"
        
    def build_frontend(self, clean: bool = True) -> bool:
        """
        Build frontend: npm install, npm run build
        
        Args:
            clean: Clean node_modules and caches before build
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"🔨 Building frontend for {self.project_name}")
        
        if not self.frontend_path.exists():
            logger.error(f"Frontend directory not found: {self.frontend_path}")
            return False
        
        env = os.environ.copy()
        
        try:
            # Step 1: Clean caches if requested
            if clean:
                self._clean_frontend_caches()
            
            # Step 2: npm install
            logger.info("📦 Installing dependencies...")
            install_result = subprocess.run(
                ["npm", "install"],
                cwd=str(self.frontend_path),
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes
                env=env
            )
            
            if install_result.returncode != 0:
                logger.error(f"npm install failed: {install_result.stderr[:500]}")
                return False
            
            logger.info("✓ npm install completed")
            
            # Step 3: npm run build
            logger.info("🏗️ Building production bundle...")
            build_result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(self.frontend_path),
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes
                env=env
            )
            
            if build_result.returncode != 0:
                logger.error(f"npm run build failed: {build_result.stderr[:500]}")
                return False
            
            # Step 4: Verify dist directory
            dist_path = self.frontend_path / "dist"
            if not dist_path.exists():
                logger.error("Build completed but dist directory not found")
                return False
            
            index_html = dist_path / "index.html"
            if not index_html.exists():
                logger.error("Build completed but index.html not found in dist")
                return False
            
            logger.info(f"✓ Frontend built successfully: {dist_path}")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Frontend build timed out after 10 minutes")
            return False
        except Exception as e:
            logger.error(f"Frontend build failed: {e}")
            return False
    
    def _clean_frontend_caches(self) -> None:
        """Clean Vite caches and optionally node_modules."""
        import shutil
        
        cache_paths = [
            self.frontend_path / "node_modules" / ".vite",
            self.frontend_path / "node_modules" / ".vite-temp",
            self.frontend_path / ".vite",
        ]
        
        for cache_path in cache_paths:
            if cache_path.exists():
                try:
                    shutil.rmtree(str(cache_path))
                    logger.info(f"✓ Cleaned cache: {cache_path.name}")
                except Exception as e:
                    logger.warning(f"Could not clean {cache_path}: {e}")
    
    def build_backend(self, install_deps: bool = True) -> bool:
        """
        Build backend: pip install, verify main.py
        
        Args:
            install_deps: Install Python dependencies
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"🔨 Building backend for {self.project_name}")
        
        if not self.backend_path.exists():
            logger.error(f"Backend directory not found: {self.backend_path}")
            return False
        
        try:
            # Step 1: Install Python dependencies
            if install_deps:
                requirements_path = self.backend_path / "requirements.txt"
                if requirements_path.exists():
                    logger.info("📦 Installing Python dependencies...")
                    
                    install_result = subprocess.run(
                        ["pip", "install", "--break-system-packages", "-r", "requirements.txt"],
                        cwd=str(self.backend_path),
                        capture_output=True,
                        text=True,
                        timeout=300  # 5 minutes
                    )
                    
                    if install_result.returncode != 0:
                        logger.warning(f"pip install had issues: {install_result.stderr[:300]}")
                    else:
                        logger.info("✓ Python dependencies installed")
                else:
                    logger.warning("No requirements.txt found, skipping dependency install")
            
            # Step 2: Verify main.py exists
            main_py = self.backend_path / "main.py"
            if not main_py.exists():
                logger.error("main.py not found in backend directory")
                return False
            
            logger.info("✓ Backend verified successfully")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Backend build timed out")
            return False
        except Exception as e:
            logger.error(f"Backend build failed: {e}")
            return False
    
    def restart_pm2_service(self, service_type: str = "all") -> bool:
        """
        Restart PM2 services for the project.
        
        Args:
            service_type: 'frontend', 'backend', or 'all'
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"🔄 Restarting PM2 services ({service_type})...")
        
        try:
            services_to_restart = []
            
            if service_type in ("frontend", "all"):
                services_to_restart.append(f"{self.project_name}-frontend")
            
            if service_type in ("backend", "all"):
                services_to_restart.append(f"{self.project_name}-backend")
            
            for service in services_to_restart:
                # Check if service exists
                list_result = subprocess.run(
                    ["pm2", "list"],
                    capture_output=True,
                    text=True
                )
                
                if service in list_result.stdout:
                    # Restart existing service
                    logger.info(f"Restarting {service}...")
                    restart_result = subprocess.run(
                        ["pm2", "restart", service],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    if restart_result.returncode != 0:
                        logger.warning(f"Failed to restart {service}: {restart_result.stderr}")
                    else:
                        logger.info(f"✓ Restarted {service}")
                else:
                    logger.warning(f"Service {service} not found in PM2")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to restart PM2 services: {e}")
            return False
    
    def restart_nginx(self) -> bool:
        """
        Reload nginx configuration.
        
        Returns:
            True if successful, False otherwise
        """
        logger.info("🔄 Reloading nginx...")
        
        try:
            # Test nginx configuration
            test_result = subprocess.run(
                ["/usr/sbin/nginx", "-t"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if test_result.returncode != 0:
                logger.error(f"Nginx config test failed: {test_result.stderr}")
                return False
            
            # Reload nginx
            reload_result = subprocess.run(
                ["/usr/bin/systemctl", "reload", "nginx"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if reload_result.returncode != 0:
                logger.error(f"Failed to reload nginx: {reload_result.stderr}")
                return False
            
            logger.info("✓ Nginx reloaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reload nginx: {e}")
            return False
    
    def publish(self, 
                build_frontend: bool = True,
                build_backend: bool = True,
                restart_pm2: bool = True,
                restart_nginx: bool = False) -> Tuple[bool, dict]:
        """
        Full build and publish workflow.
        
        Args:
            build_frontend: Build frontend
            build_backend: Build backend
            restart_pm2: Restart PM2 services after build
            restart_nginx: Reload nginx after build
            
        Returns:
            Tuple of (overall_success, results_dict)
        """
        results = {
            "frontend_build": None,
            "backend_build": None,
            "pm2_restart": None,
            "nginx_reload": None,
            "overall": False
        }
        
        logger.info(f"🚀 Starting build & publish for {self.project_name}")
        logger.info(f"   Frontend path: {self.frontend_path}")
        logger.info(f"   Backend path: {self.backend_path}")
        
        # Build frontend
        if build_frontend:
            results["frontend_build"] = self.build_frontend()
            if not results["frontend_build"]:
                logger.error("❌ Frontend build failed")
        
        # Build backend
        if build_backend:
            results["backend_build"] = self.build_backend()
            if not results["backend_build"]:
                logger.error("❌ Backend build failed")
        
        # Restart PM2 services
        if restart_pm2:
            service_type = "all" if (build_frontend and build_backend) else ("frontend" if build_frontend else "backend")
            results["pm2_restart"] = self.restart_pm2_service(service_type)
        
        # Reload nginx
        if restart_nginx:
            results["nginx_reload"] = self.restart_nginx()
        
        # Determine overall success
        build_success = True
        if build_frontend and not results["frontend_build"]:
            build_success = False
        if build_backend and not results["backend_build"]:
            build_success = False
        
        results["overall"] = build_success
        
        # Summary
        logger.info("=" * 50)
        logger.info("📊 Build & Publish Summary:")
        logger.info(f"   Frontend build: {'✓' if results['frontend_build'] else '✗' if build_frontend else '—'}")
        logger.info(f"   Backend build:  {'✓' if results['backend_build'] else '✗' if build_backend else '—'}")
        logger.info(f"   PM2 restart:    {'✓' if results['pm2_restart'] else '✗' if restart_pm2 else '—'}")
        logger.info(f"   Nginx reload:   {'✓' if results['nginx_reload'] else '✗' if restart_nginx else '—'}")
        logger.info(f"   Overall:        {'✅ SUCCESS' if results['overall'] else '❌ FAILED'}")
        logger.info("=" * 50)
        
        return results["overall"], results


def main():
    parser = argparse.ArgumentParser(
        description="Build and publish DreamPilot projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python buildpublish.py --project myapp --frontend
    python buildpublish.py --project myapp --backend
    python buildpublish.py --project myapp --frontend --backend
    python buildpublish.py --project myapp --all --restart-nginx
        """
    )
    
    parser.add_argument(
        "--project", "-p",
        required=True,
        help="Project name (folder name in /root/dreampilot/projects/website/)"
    )
    
    parser.add_argument(
        "--frontend", "-f",
        action="store_true",
        help="Build frontend (npm install, npm run build)"
    )
    
    parser.add_argument(
        "--backend", "-b",
        action="store_true",
        help="Build backend (pip install, verify)"
    )
    
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Build both frontend and backend"
    )
    
    parser.add_argument(
        "--restart-pm2",
        action="store_true",
        default=True,
        help="Restart PM2 services after build (default: True)"
    )
    
    parser.add_argument(
        "--no-restart-pm2",
        action="store_true",
        help="Do not restart PM2 services"
    )
    
    parser.add_argument(
        "--restart-nginx", "-n",
        action="store_true",
        help="Reload nginx after build"
    )
    
    parser.add_argument(
        "--clean", "-c",
        action="store_true",
        default=True,
        help="Clean caches before build (default: True)"
    )
    
    args = parser.parse_args()
    
    # Determine what to build
    build_frontend = args.frontend or args.all
    build_backend = args.backend or args.all
    
    if not build_frontend and not build_backend:
        logger.error("Specify what to build: --frontend, --backend, or --all")
        sys.exit(1)
    
    # Handle PM2 restart flag
    restart_pm2 = not args.no_restart_pm2 if args.no_restart_pm2 else args.restart_pm2
    
    # Create publisher and run
    publisher = BuildPublisher(args.project)
    
    success, results = publisher.publish(
        build_frontend=build_frontend,
        build_backend=build_backend,
        restart_pm2=restart_pm2,
        restart_nginx=args.restart_nginx
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
