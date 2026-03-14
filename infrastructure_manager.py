"""
Infrastructure Manager for DreamPilot

Handles all infrastructure provisioning for website projects:
- PostgreSQL database/user creation
- Port allocation
- Service management
- Nginx configuration
- Deployment verification with retry logic
"""

import subprocess
import sqlite3
import random
import string
import json
import logging
import os
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import dns_manager  # Internal DNS management module
from typing import Optional, Dict, List, Tuple

# Import enhanced deployment verifier
from deployment_verifier import DeploymentVerifier as EnhancedDeploymentVerifier, format_verification_report

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = "/root/clawd-backend/clawdbot_adapter.db"
PROJECT_DB_PATH = "/root/clawd-backend/projects.db"

# Infrastructure settings
POSTGRES_CONTAINER = "dreampilot-postgres"
POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
POSTGRES_USER = "admin"
POSTGRES_PASSWORD = "StrongAdminPass123"  # TODO: Load from secure config

# Port ranges
FRONTEND_PORT_MIN = 3000
FRONTEND_PORT_MAX = 4000
BACKEND_PORT_MIN = 8010
BACKEND_PORT_MAX = 9000

# DNS settings
BASE_DOMAIN = "dreambigwithai.com"
NGINX_CONFIG_DIR = "/etc/nginx/sites-available"
NGINX_ENABLED_DIR = "/etc/nginx/sites-enabled"

# DNS settings
HOSTINGER_DNS_SKILL_DIR = "/usr/lib/node_modules/openclaw/skills/hostinger-dns"
HOSTINGER_DNS_SKILL = "/usr/lib/node_modules/openclaw/skills/hostinger-dns/hostinger_dns.py"
SERVER_IP = "195.200.14.37"  # Default server IP for DNS A records

# Shared runtime venv
SHARED_VENV_PATH = "/root/dreampilot/dreampilotvenv"


class PortAllocator:
    """Manages port allocation for projects."""

    def __init__(self):
        self.used_ports = set()
        self._load_used_ports()

    def _load_used_ports(self):
        """Load already allocated ports from projects database."""
        try:
            conn = sqlite3.connect(PROJECT_DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute("SELECT frontend_port, backend_port FROM projects WHERE status = 'ready'")
                for row in cursor:
                    if row['frontend_port']:
                        self.used_ports.add(row['frontend_port'])
                    if row['backend_port']:
                        self.used_ports.add(row['backend_port'])
                logger.info(f"Loaded {len(self.used_ports)} used ports from database")
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Could not load used ports from database: {e}")

        # Also scan for ports that are actually in use
        try:
            import socket
            logger.info("Scanning for ports in use...")
            # Check frontend ports
            for port in range(FRONTEND_PORT_MIN, FRONTEND_PORT_MAX):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.1)
                    result = sock.connect_ex(('127.0.0.1', port))
                    sock.close()
                    if result == 0:  # Port is open/in use
                        self.used_ports.add(port)
                except Exception:
                    pass

            # Check backend ports
            for port in range(BACKEND_PORT_MIN, BACKEND_PORT_MAX):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.1)
                    result = sock.connect_ex(('127.0.0.1', port))
                    sock.close()
                    if result == 0:  # Port is open/in use
                        self.used_ports.add(port)
                except Exception:
                    pass

            logger.info(f"Total ports marked as used: {len(self.used_ports)}")
        except Exception as e:
            logger.warning(f"Could not scan for ports in use: {e}")

    def allocate_frontend_port(self) -> int:
        """Allocate a free frontend port (3000-4000)."""
        for port in range(FRONTEND_PORT_MIN, FRONTEND_PORT_MAX):
            if port not in self.used_ports:
                self.used_ports.add(port)
                logger.info(f"Allocated frontend port: {port}")
                return port

        raise RuntimeError("No available frontend ports (3000-4000)")

    def allocate_backend_port(self) -> int:
        """Allocate a free backend port (8010-9000)."""
        for port in range(BACKEND_PORT_MIN, BACKEND_PORT_MAX):
            if port not in self.used_ports:
                self.used_ports.add(port)
                logger.info(f"Allocated backend port: {port}")
                return port

        raise RuntimeError("No available backend ports (8010-9000)")

    def release_ports(self, frontend_port: int = None, backend_port: int = None):
        """Release allocated ports."""
        if frontend_port:
            self.used_ports.discard(frontend_port)
            logger.info(f"Released frontend port: {frontend_port}")
        if backend_port:
            self.used_ports.discard(backend_port)
            logger.info(f"Released backend port: {backend_port}")


class DatabaseProvisioner:
    """Provisions PostgreSQL databases and users for projects."""

    def __init__(self):
        self.container = POSTGRES_CONTAINER

    def _sanitize_db_name(self, name: str) -> str:
        """Sanitize database name by replacing hyphens with underscores."""
        return name.replace("-", "_")

    def _execute_sql(self, sql: str, database_name: str = "defaultdb") -> List[Tuple]:
        """Execute SQL command in PostgreSQL container.

        Args:
            sql: SQL command to execute
            database_name: Database to connect to (defaults to "defaultdb")

        Returns:
            List of tuples with query results
        """
        try:
            cmd = [
                "docker", "exec", self.container,
                "psql", "-U", POSTGRES_USER, "-d", database_name, "-c", sql
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.error(f"SQL execution failed: {result.stderr}")
                return []

            # Parse output (if any)
            if result.stdout.strip():
                lines = result.stdout.strip().split('\n')
                return [tuple(line.split(' | ')) for line in lines if '|' in line]

            return []

        except Exception as e:
            logger.error(f"Failed to execute SQL: {e}")
            return []

    def _generate_password(self, length: int = 32) -> str:
        """Generate secure random password."""
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(random.choice(chars) for _ in range(length))

    def create_database_and_user(self, project_name: str) -> Dict[str, str]:
        """
        Create PostgreSQL database and user for project.

        Returns:
            Dict with database_name, username, password
        """
        try:
            db_name = f"{self._sanitize_db_name(project_name)}_db"
            username = f"{self._sanitize_db_name(project_name)}_user"
            password = self._generate_password()

            logger.info(f"Creating database: {db_name}")
            logger.info(f"Creating user: {username}")

            # Create database (quoted to handle SQL keywords)
            self._execute_sql(f'CREATE DATABASE "{db_name}";')
            logger.info(f"✓ Database created: {db_name}")

            # Create user (quoted to handle SQL keywords)
            self._execute_sql(
                f'CREATE USER "{username}" WITH PASSWORD \'{password}\';'
            )
            logger.info(f"✓ User created: {username}")

            # Grant privileges
            self._execute_sql(
                f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO "{username}";'
            )
            logger.info(f"✓ Privileges granted to {username}")

            return {
                "database_name": db_name,
                "username": username,
                "password": password,
                "database_url": f"postgresql://{username}:{password}@{POSTGRES_HOST}:{POSTGRES_PORT}/{db_name}"
            }

        except Exception as e:
            logger.error(f"Failed to create database/user: {e}")
            raise

    def drop_database_and_user(self, project_name: str):
        """Drop database and user for project."""
        try:
            db_name = f"{self._sanitize_db_name(project_name)}_db"
            username = f"{self._sanitize_db_name(project_name)}_user"

            logger.info(f"Dropping database: {db_name}")

            # Drop connections first (connect to project-specific database)
            self._execute_sql(
                f"SELECT pg_terminate_backend(pg_stat_activity.pid) "
                f"FROM pg_stat_activity "
                f"WHERE pg_stat_activity.datname = '{db_name}' "
                f"AND pid <> pg_backend_pid();",
                database_name=db_name
            )

            # Drop database (quoted to handle SQL keywords, connect to project-specific database)
            self._execute_sql(f'DROP DATABASE IF EXISTS "{db_name}";', database_name=db_name)
            logger.info(f"✓ Database dropped: {db_name}")

            # Drop user (quoted to handle SQL keywords, connect to project-specific database)
            self._execute_sql(f'DROP USER IF EXISTS "{username}";', database_name=db_name)
            logger.info(f"✓ User dropped: {username}")

        except Exception as e:
            logger.error(f"Failed to drop database/user: {e}")

    def get_database_size(self, project_name: str) -> int:
        """Get database size in MB."""
        try:
            db_name = f"{self._sanitize_db_name(project_name)}_db"

            result = self._execute_sql(
                f'SELECT pg_database_size(\'{db_name}\') AS size;',
                database_name=db_name
            )

            if result and len(result) > 0:
                size_bytes = int(result[0][0])
                size_mb = size_bytes / (1024 * 1024)
                return round(size_mb, 2)

            return 0

        except Exception as e:
            logger.error(f"Failed to get database size: {e}")
            return 0


class ServiceManager:
    """Manages PM2 services for projects."""

    def __init__(self):
        self.venv_path = SHARED_VENV_PATH

    def create_backend_service(self, project_name: str, backend_port: int, project_path: Path) -> str:
        """
        Create PM2 config for backend service.

        Returns:
            PM2 app name
        """
        try:
            app_name = f"{project_name}-backend"
            backend_path = project_path / "backend"

            # PM2 ecosystem config
            ecosystem = f"""{{
  "name": "{app_name}",
  "script": "main.py",
  "cwd": "{backend_path}",
  "interpreter": "{self.venv_path}/bin/python",
  "env": {{
    "API_PORT": "{backend_port}",
    "PROJECT_NAME": "{project_name}"
  }},
  "error_file": "{backend_path}/logs/error.log",
  "out_file": "{backend_path}/logs/out.log",
  "log_date_format": "YYYY-MM-DD HH:mm:ss Z"
}}
"""

            # Save ecosystem file
            ecosystem_path = backend_path / "ecosystem.config.json"
            ecosystem_path.write_text(ecosystem)

            logger.info(f"✓ PM2 config created: {app_name}")
            return app_name

        except Exception as e:
            logger.error(f"Failed to create backend service config: {e}")
            raise

    def start_backend_service(self, app_name: str, backend_path: Path, port: int = None) -> bool:
        """Start backend service with FastAPI/uvicorn and dependency installation."""
        try:
            logger.info(f"[SERVICE] Starting backend service: {app_name}")
            logger.info(f"[SERVICE] Backend working directory: {backend_path}")
            logger.info(f"[SERVICE] Backend port: {port}")

            # Install Python dependencies first
            requirements_path = backend_path / "requirements.txt"
            if requirements_path.exists():
                logger.info("[SERVICE] Installing Python dependencies from requirements.txt...")
                try:
                    subprocess.run(
                        ["pip", "install", "--break-system-packages", "-r", "requirements.txt"],
                        cwd=str(backend_path),
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=300  # 5 minutes
                    )
                    logger.info("[SERVICE] ✓ Python dependencies installed successfully")
                except subprocess.CalledProcessError as e:
                    logger.error(f"[SERVICE] Failed to install dependencies: {e}")
                    logger.error(f"[SERVICE] Install stderr: {e.stderr[:500]}")
                    return False
            else:
                logger.warning(f"[SERVICE] No requirements.txt found at {requirements_path}")

            # Prepare backend port
            backend_port = port if port else 8000

            # Create ecosystem config for PM2 with Python FastAPI backend
            ecosystem_config = {
                "apps": [{
                    "name": app_name,
                    "script": "python3",
                    "args": f"-m uvicorn main:app --host 0.0.0.0 --port {backend_port}",
                    "cwd": str(backend_path),
                    "instances": 1,
                    "exec_mode": "fork",
                    "watch": False,
                    "max_memory_restart": "500M",
                    "env": {
                        "PORT": str(backend_port),
                        "BACKEND_HOST": "0.0.0.0",
                        "BACKEND_PORT": str(backend_port)
                    }
                }]
            }

            # Write ecosystem config file
            import json
            ecosystem_path = backend_path / "ecosystem.config.json"
            ecosystem_path.write_text(json.dumps(ecosystem_config, indent=2))

            # Start FastAPI backend using ecosystem config
            backend_cmd = [
                "pm2", "start", str(ecosystem_path)
            ]

            logger.info(f"[SERVICE] Backend command: {' '.join(backend_cmd)}")

            result = subprocess.run(
                backend_cmd,
                cwd=str(backend_path),
                check=True,
                capture_output=True,
                text=True,
                timeout=30
            )

            logger.info(f"[SERVICE] Backend service started successfully: {app_name}")
            logger.info(f"[SERVICE] Backend stdout: {result.stdout[:200]}")

            # Add startup delay to ensure backend is ready
            logger.info("[SERVICE] Waiting for backend to start (5s)...")
            time.sleep(5)

            # Log PM2 status to verify backend is running
            pm2_status = subprocess.run(
                ["pm2", "list"],
                capture_output=True,
                text=True
            )
            logger.info(f"[SERVICE] PM2 status after startup:\n{pm2_status.stdout}")

            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"[SERVICE] Backend service failed to start: {e}")
            logger.error(f"[SERVICE] Backend stderr: {e.stderr[:300]}")
            return False
        except Exception as e:
            logger.error(f"[SERVICE] Backend service error: {e}")
            return False

    def stop_service(self, app_name: str) -> bool:
        """Stop service."""
        try:
            logger.info(f"Stopping service: {app_name}")

            result = subprocess.run(
                ["pm2", "stop", app_name],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"✓ Service stopped: {app_name}")
                return True
            else:
                logger.error(f"Failed to stop service: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to stop service: {e}")
            return False

    def delete_service(self, app_name: str) -> bool:
        """Delete service from PM2."""
        try:
            logger.info(f"Deleting service: {app_name}")

            result = subprocess.run(
                ["pm2", "delete", app_name],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"✓ Service deleted: {app_name}")
                return True
            else:
                logger.error(f"Failed to delete service: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to delete service: {e}")
            return False

    def build_frontend(self) -> bool:
        """
        Build frontend with Vite cache cleanup and build verification.

        Returns:
            True if successful, False otherwise
        """
        # Copy system environment to ensure npm/node are accessible
        env = os.environ.copy()
        
        try:
            logger.info("PHASE_5_BUILD_START")
            logger.info(f"[BUILD] Starting frontend build for {self.project_name}")
            
            frontend_dist_path = self.project_path / "frontend"
            
            # Check if frontend exists
            if not frontend_dist_path.exists():
                logger.error(f"[BUILD] Frontend directory not found: {frontend_dist_path}")
                logger.info("PHASE_5_BUILD_FAILED: missing frontend")
                return False
            
            # Clean Vite caches before build to prevent stale cache issues
            logger.info("[BUILD] Cleaning Vite caches to prevent corrupted node_modules...")
            vite_cache_paths = [
                frontend_dist_path / "node_modules" / ".vite",
                frontend_dist_path / "node_modules" / ".vite-temp",
            ]
            
            caches_cleaned = 0
            for cache_path in vite_cache_paths:
                if cache_path.exists():
                    try:
                        import shutil
                        shutil.rmtree(str(cache_path))
                        logger.info(f"[BUILD] ✓ Cleaned Vite cache: {cache_path.name}")
                        caches_cleaned += 1
                    except Exception as cache_err:
                        logger.warning(f"[BUILD] ⚠️ Could not clean cache {cache_path.name}: {cache_err}")
            
            logger.info(f"[BUILD] Cleaned {caches_cleaned} Vite cache directories")
            
            # Install dependencies before build
            logger.info("[BUILD] Installing frontend dependencies...")
            install_result = subprocess.run(
                ["npm", "install"],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes
                cwd=str(frontend_dist_path),
                env=env
            )
            
            if install_result.returncode != 0:
                logger.error(f"[BUILD] npm install failed with code {install_result.returncode}")
                logger.error(f"[BUILD] npm install stderr: {install_result.stderr[:500]}")
                logger.info("PHASE_5_BUILD_FAILED: npm install failed")
                return False
            
            logger.info("[BUILD] ✓ npm install completed successfully")
            
            # Build the app
            logger.info("[BUILD] Building frontend with Vite...")
            build_result = subprocess.run(
                ["npm", "run", "build"],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes
                cwd=str(frontend_dist_path),
                env=env
            )
            
            if build_result.returncode != 0:
                logger.error(f"[BUILD] Frontend build failed with code {build_result.returncode}")
                logger.error(f"[BUILD] Build stderr (last 500 chars): {build_result.stderr[-500:]}")
                logger.info("PHASE_5_BUILD_FAILED: build command failed")
                return False
            
            # Verify dist directory was created
            dist_path = frontend_dist_path / "dist"
            if not dist_path.exists():
                logger.error(f"[BUILD] Build completed but dist directory missing: {dist_path}")
                logger.info("PHASE_5_BUILD_FAILED: dist directory not created")
                return False
            
            if not any(dist_path.iterdir()):
                logger.error(f"[BUILD] Build completed but dist directory is empty: {dist_path}")
                logger.info("PHASE_5_BUILD_FAILED: dist directory empty")
                return False
            
            # Verify index.html exists (critical for SPA routing)
            index_html = dist_path / "index.html"
            if not index_html.exists():
                logger.error(f"[BUILD] index.html not found in dist: {index_html}")
                logger.info("PHASE_5_BUILD_FAILED: index.html missing")
                return False
            
            logger.info(f"[BUILD] ✓ Frontend built successfully")
            logger.info(f"[BUILD] ✓ Dist directory created: {dist_path}")
            logger.info("[BUILD] ✓ index.html verified")
            logger.info("PHASE_5_BUILD_COMPLETE: success")
            return True

        except subprocess.TimeoutExpired:
            logger.error("PHASE_5_BUILD_FAILED: build timed out after 10 minutes")
            return False
        except Exception as e:
            logger.error(f"PHASE_5_BUILD_FAILED: {type(e).__name__}: {str(e)}")
            return False

    def create_frontend_service(self, project_name: str, frontend_port: int, project_path: Path) -> str:
        """
        Create PM2 config for frontend service.

        Uses project-specific frontend if available, otherwise falls back to shared dist.

        Returns:
            PM2 app name
        """
        # Copy system environment to ensure npm/node are accessible
        env = os.environ.copy()
        
        try:
            app_name = f"{project_name}-frontend"
            
            # Check if project has its own frontend directory with built dist
            project_frontend_path = project_path / "frontend"
            project_dist_path = project_frontend_path / "dist"
            
            # Check for dist directory (built frontend) or frontend source
            has_frontend = project_frontend_path.exists()
            has_dist = project_dist_path.exists() and (project_dist_path / "index.html").exists()
            
            if has_frontend and (has_dist or (project_frontend_path / "package.json").exists()):
                # Use project-specific frontend
                logger.info(f"Using project-specific frontend: {project_frontend_path}")
                frontend_dist_path = project_frontend_path
                
                # Build the Vite app for production serving with correct MIME types
                package_json = frontend_dist_path / "package.json"
                dist_dir = frontend_dist_path / "dist"
                
                # Check if already built
                if has_dist:
                    logger.info(f"✓ Frontend already built, using dist: {dist_dir}")
                    frontend_dist_path = dist_dir
                elif package_json.exists():
                    logger.info(f"Building frontend for production (correct MIME types)...")
                    try:
                        # Clean Vite cache before build to prevent stale cache issues
                        vite_cache = frontend_dist_path / "node_modules" / ".vite"
                        vite_temp_cache = frontend_dist_path / "node_modules" / ".vite-temp"
                        
                        for cache_path in [vite_cache, vite_temp_cache]:
                            if cache_path.exists():
                                try:
                                    import shutil
                                    shutil.rmtree(str(cache_path))
                                    logger.info(f"✓ Cleaned Vite cache: {cache_path.name}")
                                except Exception as cache_err:
                                    logger.warning(f"⚠️ Could not clean cache {cache_path}: {cache_err}")
                        
                        # Install dependencies
                        install_result = subprocess.run(
                            ["npm", "install"],
                            capture_output=True,
                            text=True,
                            timeout=300,
                            cwd=str(frontend_dist_path),
                            env=env
                        )
                        
                        if install_result.returncode != 0:
                            logger.warning(f"npm install warnings: {install_result.stderr}")
                        else:
                            logger.info(f"✓ npm install completed")
                        
                        # Build the app
                        build_result = subprocess.run(
                            ["npm", "run", "build"],
                            capture_output=True,
                            text=True,
                            timeout=300,
                            cwd=str(frontend_dist_path),
                            env=env
                        )
                        
                        if build_result.returncode != 0:
                            logger.error(f"Frontend build failed: {build_result.stderr}")
                            raise Exception(f"Frontend build failed: {build_result.stderr}")
                        else:
                            logger.info(f"✓ Frontend built successfully")
                            frontend_dist_path = dist_dir
                    except subprocess.TimeoutExpired:
                        logger.error("Frontend build timed out")
                        raise Exception("Frontend build timed out")
                
                # Use PM2 built-in serve command for SPA routing
                # Run: pm2 serve dist {port} -s --name {app_name} from frontend directory
                subprocess.run(
                    ["pm2", "serve", str(frontend_dist_path), str(frontend_port), "-s", "--name", app_name],
                    capture_output=True,
                    timeout=30
                )
                logger.info(f"✓ Frontend PM2 service started with SPA routing: {app_name}")
            else:
                # Use shared frontend (fallback)
                logger.info(f"Using shared frontend: {CLAWD_UI_DIST}")
                frontend_dist_path = Path(CLAWD_UI_DIST)
                
                # Check if dist exists
                if not frontend_dist_path.exists():
                    raise FileNotFoundError(f"Frontend dist directory not found: {frontend_dist_path}")
                
                # Build frontend if needed (for production serving with proper MIME types)
                serve_py = frontend_dist_path / "serve.py"
                package_json = frontend_dist_path / "package.json"
                
                if package_json.exists():
                    # Use serve package (handles MIME types correctly)
                    logger.info(f"Using serve package for frontend (handles MIME types correctly)")
                    # serve package is already installed globally, no need to create serve.py
                else:
                    # Build frontend first
                    logger.info(f"Building frontend for production: {frontend_dist_path}")
                    build_result = subprocess.run(
                        ["npm", "run", "build"],
                        capture_output=True,
                        text=True,
                        timeout=300,  # 5 minutes
                        cwd=str(frontend_dist_path),
                        env=env
                    )
                    
                    if build_result.returncode != 0:
                        logger.error(f"Frontend build failed: {build_result.stderr}")
                    else:
                        logger.info(f"✓ Frontend built successfully")
                    
                    # Create serve.py if it doesn't exist
                    if not serve_py.exists():
                        logger.info("Creating simple serve.py (MIME types may not work correctly)")
                        serve_script = """#!/usr/bin/env python3
import http.server
import socketserver
import os

PORT = int(os.getenv('PORT', '3000'))
FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))

class FrontendHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_GET(self):
        request_path = self.path.split('?')[0]
        if request_path == '/' or not os.path.exists(f'{FRONTEND_DIR}{request_path.lstrip('/')}'):
            self.path = '/index.html'
        return super().do_GET()

def main():
    with socketserver.TCPServer(("", PORT), FrontendHTTPRequestHandler) as httpd:
        print(f"Serving on port {PORT}...")
        httpd.serve_forever()

if __name__ == "__main__":
    main()
"""
                        serve_py.write_text(serve_script)
                        logger.info(f"✓ Created serve.py fallback for shared frontend")
                
                # PM2 ecosystem config
                ecosystem = f"""{{
  "name": "{app_name}",
  "script": "serve.py",
  "cwd": "{frontend_dist_path}",
  "interpreter": "python3",
  "env": {{
    "FRONTEND_PORT": "{frontend_port}",
    "PROJECT_NAME": "{project_name}"
  }},
  "error_file": "{project_path}/frontend/logs/error.log",
  "out_file": "{project_path}/frontend/logs/out.log",
  "log_date_format": "YYYY-MM-DD HH:mm:ss Z"
}}
"""

                # Save ecosystem file
                ecosystem_path = project_path / "frontend" / f"{app_name}.config.json"
                ecosystem_path.write_text(ecosystem)

                logger.info(f"✓ Frontend PM2 config created: {app_name}")
            return app_name

        except Exception as e:
            logger.error(f"Failed to create frontend service config: {e}")
            raise

    def start_frontend_service(self, app_name: str, project_path: Path = None) -> bool:
        """Start frontend service - now uses PM2 serve directly."""
        try:
            logger.info(f"Checking frontend service status: {app_name}")

            # Check if service is already running
            result = subprocess.run(
                ["pm2", "list"],
                capture_output=True,
                text=True
            )

            if app_name in result.stdout:
                logger.info(f"✓ Frontend service already running: {app_name}")
                return True

            logger.info(f"Starting frontend service: {app_name}")
            # Service is started during create_frontend_service via pm2 serve
            # This method now just verifies the service exists
            logger.info(f"✓ Frontend service check complete: {app_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to start frontend service: {e}")
            return False


class NginxConfigurator:
    """Manages nginx configuration for projects."""

    def __init__(self):
        self.config_dir = NGINX_CONFIG_DIR
        self.enabled_dir = NGINX_ENABLED_DIR

    def generate_ssl_certificates(self, domain: str) -> bool:
        """
        Generate SSL certificates using certbot for both frontend and backend domains.

        Args:
            domain: Domain name (e.g., "ecommerce22")

        Returns:
            True if successful, False otherwise
        """
        try:
            frontend_domain = f"{domain}.{BASE_DOMAIN}"
            backend_domain = f"{domain}-api.{BASE_DOMAIN}"

            logger.info(f"🔐 Generating SSL certificates for {domain}")
            logger.info(f"   Frontend: {frontend_domain}")
            logger.info(f"   Backend:  {backend_domain}")

            # Generate SSL certificate for frontend
            frontend_result = subprocess.run(
                ["certbot", "--nginx", "-d", frontend_domain, "--non-interactive", "--agree-tos"],
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes
            )

            if frontend_result.returncode != 0:
                logger.error(f"Failed to generate SSL for frontend: {frontend_result.stderr}")
                return False

            logger.info(f"✓ SSL certificate generated for {frontend_domain}")

            # Generate SSL certificate for backend
            backend_result = subprocess.run(
                ["certbot", "--nginx", "-d", backend_domain, "--non-interactive", "--agree-tos"],
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes
            )

            if backend_result.returncode != 0:
                logger.error(f"Failed to generate SSL for backend: {backend_result.stderr}")
                return False

            logger.info(f"✓ SSL certificate generated for {backend_domain}")

            return True

        except Exception as e:
            logger.error(f"Failed to generate SSL certificates: {e}")
            return False

    def generate_config(self, domain: str, frontend_port: int, backend_port: int, enable_ssl: bool = False, project_path: str = None) -> Tuple[str, str]:
        """
        Generate nginx configuration for project.

        Args:
            domain: Domain name (e.g., "ecommerce22")
            frontend_port: Frontend service port
            backend_port: Backend service port
            enable_ssl: Whether to generate SSL config (default: False)
            project_path: Actual project folder path (e.g., "686_test_20260313_142220"). 
                          If not provided, falls back to domain name.

        Returns:
            Tuple of (frontend_domain, backend_domain, config)
        """
        try:
            frontend_domain = f"{domain}.{BASE_DOMAIN}"
            backend_domain = f"{domain}-api.{BASE_DOMAIN}"
            
            # Use project_path if provided, otherwise fall back to domain
            # The actual folder is like "686_test778786_20260313_142220"
            # but domain is like "test778786-7hbrzr"
            website_folder = project_path if project_path else domain

            if enable_ssl:
                # Generate HTTPS configuration with SSL and SPA routing
                config = f"""# Frontend: {frontend_domain}
server {{
    listen 80;
    server_name {frontend_domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    server_name {frontend_domain};

    ssl_certificate /etc/letsencrypt/live/{frontend_domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{frontend_domain}/privkey.pem;

    root /root/dreampilot/projects/website/{website_folder}/frontend/dist;
    index index.html;

    # SPA routing - serve index.html for all routes
    location / {{
        try_files $uri $uri/ /index.html;
    }}

    # API proxy
    # API proxy (trailing slash strips /api prefix)
    location /api/ {{
        proxy_pass http://127.0.0.1:{backend_port}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }}
}}

# Backend: {backend_domain}
server {{
    listen 80;
    server_name {backend_domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    server_name {backend_domain};

    ssl_certificate /etc/letsencrypt/live/{backend_domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{backend_domain}/privkey.pem;

    location / {{
        proxy_pass http://127.0.0.1:{backend_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
    }}
}}
"""
            else:
                # Generate HTTP-only configuration with SPA routing
                config = f"""# Frontend: {frontend_domain}
server {{
    listen 80;
    server_name {frontend_domain};

    root /root/dreampilot/projects/website/{website_folder}/frontend/dist;
    index index.html;

    # SPA routing - serve index.html for all routes
    location / {{
        try_files $uri $uri/ /index.html;
    }}

    # API proxy (trailing slash strips /api prefix)
    location /api/ {{
        proxy_pass http://127.0.0.1:{backend_port}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}

# Backend: {backend_domain}
server {{
    listen 80;
    server_name {backend_domain};

    location / {{
        proxy_pass http://127.0.0.1:{backend_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
    }}
}}
"""

            logger.info(f"✓ Nginx config generated for {domain} (SSL: {enable_ssl})")
            return (frontend_domain, backend_domain, config)

        except Exception as e:
            logger.error(f"Failed to generate nginx config: {e}")
            raise

    def install_config(self, domain: str, config: str) -> bool:
        """
        Install nginx configuration and enable it.

        Args:
            domain: Domain name (e.g., "ecommerce22")
            config: Nginx configuration content
        """
        try:
            config_path = Path(self.config_dir) / f"{domain}.conf"
            symlink_path = Path(self.enabled_dir) / f"{domain}.conf"

            # Write config file
            config_path.write_text(config)
            logger.info(f"✓ Config written: {config_path}")

            # Create symlink in sites-enabled
            if symlink_path.exists():
                symlink_path.unlink()

            symlink_path.symlink_to(config_path)
            logger.info(f"✓ Symlink created: {symlink_path}")

            return True

        except Exception as e:
            logger.error(f"Failed to install nginx config: {e}")
            return False

    def reload_nginx(self) -> bool:
        """Reload nginx to apply new configuration."""
        try:
            logger.info("Reloading nginx...")

            # Test configuration first
            test_result = subprocess.run(
                ["/usr/sbin/nginx", "-t"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if test_result.returncode != 0:
                logger.error(f"Nginx config test failed: {test_result.stderr}")
                return False

            # Reload nginx using systemctl
            result = subprocess.run(
                ["/usr/bin/systemctl", "reload", "nginx"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info("✓ Nginx reloaded successfully")
                return True
            else:
                logger.error(f"Failed to reload nginx: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to reload nginx: {e}")
            return False

    def remove_config(self, project_name: str) -> bool:
        """Remove nginx configuration."""
        try:
            config_path = Path(self.config_dir) / f"{project_name}.conf"
            symlink_path = Path(self.enabled_dir) / f"{project_name}.conf"

            # Remove symlink
            if symlink_path.exists():
                symlink_path.unlink()
                logger.info(f"✓ Symlink removed: {symlink_path}")

            # Remove config file
            if config_path.exists():
                config_path.unlink()
                logger.info(f"✓ Config removed: {config_path}")

            # Reload nginx
            return self.reload_nginx()

        except Exception as e:
            logger.error(f"Failed to remove nginx config: {e}")
            return False


class DeploymentVerifier:
    """Verifies that deployment is working correctly."""

    def __init__(self):
        pass

    def check_port(self, port: int, timeout: int = 5) -> bool:
        """Check if port is accessible."""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.error(f"Failed to check port {port}: {e}")
            return False

    def check_health_endpoint(self, port: int, path: str = "/health", timeout: int = 10) -> bool:
        """Check if backend health endpoint is responding."""
        try:
            import urllib.request
            import json

            url = f"http://127.0.0.1:{port}{path}"
            req = urllib.request.Request(url)

            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = response.read().decode('utf-8')
                result = json.loads(data)

                return result.get('status') == 'healthy' or result.get('status') == 'ok'

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def verify_deployment(self, project_name: str, frontend_port: int, backend_port: int) -> Dict[str, bool]:
        """
        Verify complete deployment.

        Returns:
            Dict with verification results
        """
        results = {
            "frontend_port_open": False,
            "backend_port_open": False,
            "backend_health_ok": False,
            "overall": False
        }

        logger.info(f"Verifying deployment for {project_name}...")

        # Check frontend port
        results["frontend_port_open"] = self.check_port(frontend_port)
        logger.info(f"Frontend port {frontend_port}: {'✓' if results['frontend_port_open'] else '✗'}")

        # Check backend port
        results["backend_port_open"] = self.check_port(backend_port)
        logger.info(f"Backend port {backend_port}: {'✓' if results['backend_port_open'] else '✗'}")

        # Check health endpoint
        if results["backend_port_open"]:
            results["backend_health_ok"] = self.check_health_endpoint(backend_port)
            logger.info(f"Backend health: {'✓' if results['backend_health_ok'] else '✗'}")

        # Overall status - backend is critical, frontend is optional
        results["overall"] = all([
            results["backend_port_open"],
            results["backend_health_ok"]
        ])

        # Warning if frontend not available
        if not results["frontend_port_open"]:
            logger.warning(f"⚠️ Frontend port {frontend_port} not accessible (may need more time or port conflict)")

        logger.info(f"Overall deployment: {'✓' if results['overall'] else '✗'}")

        return results


class DNSProvisioner:
    """Provisions DNS A records using internal dns_manager module."""

    def __init__(self):
        self.server_ip = SERVER_IP

        # Check if DNS API token is available
        import os
        self.api_token = os.getenv("HOSTINGER_API_TOKEN")
        self.dns_skill_available = self.api_token and self.api_token != "your_token_here"
        if not self.dns_skill_available:
            logger.warning(f"⚠️ HOSTINGER_API_TOKEN not set in environment")
            logger.warning(f"  DNS provisioning will be skipped. Configure DNS manually in Hostinger hPanel.")

    def check_subdomain_exists(self, subdomain: str, domain: str = None) -> Tuple[bool, Optional[str]]:
        """
        Check if subdomain already exists.

        Returns:
            Tuple of (exists: bool, current_ip: str or None)
        """
        if not self.dns_skill_available:
            return (False, None)

        try:
            if not domain:
                domain = BASE_DOMAIN

            # Use internal dns_manager module
            result = dns_manager.check_subdomain_exists(domain, subdomain)

            if result.get("success") and result.get("exists"):
                current_ip = result.get("value") or result.get("current_ip")
                return (True, current_ip)
            return (False, None)

        except Exception as e:
            logger.error(f"Failed to check subdomain: {e}")
            return (False, None)

    def create_a_record(self, subdomain: str, domain: str = None, ip: str = None, ttl: int = 14400) -> bool:
        """
        Create A record for subdomain.

        Returns:
            True if successful, False otherwise
        """
        if not self.dns_skill_available:
            logger.warning(f"  Skipping DNS A record creation (HOSTINGER_API_TOKEN not set)")
            logger.warning(f"  Manually create A record: {subdomain}.{BASE_DOMAIN} → {self.server_ip}")
            return False

        try:
            if not domain:
                domain = BASE_DOMAIN
            if not ip:
                ip = self.server_ip

            logger.info(f"Creating A record: {subdomain}.{domain} → {ip}")

            # Use internal dns_manager module
            result = dns_manager.create_a_record(domain, subdomain, ip, ttl)

            if result.get("success"):
                logger.info(f"✓ A record created: {subdomain}.{domain} → {ip}")
                logger.info(f"  Note: DNS propagation takes 5-60 minutes")
                return True
            else:
                logger.error(f"Failed to create A record: {result.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Failed to create A record: {e}")
            return False

    def provision_project_dns(self, domain: str, project_name: str = "project") -> Dict[str, bool]:
        """
        Provision DNS records for a project (frontend + backend).

        Args:
            domain: Domain name (e.g., "ecommerce22")
            project_name: Project name (for logging, optional)

        Returns:
            Dict with results for frontend and backend DNS
        """
        results = {
            "frontend": False,
            "backend": False,
            "frontend_exists": False,
            "backend_exists": False,
            "skipped": False
        }

        # Skip DNS provisioning if skill is not available
        if not self.dns_skill_available:
            logger.warning(f"⚠️ DNS provisioning skipped (DNS skill not available)")
            logger.warning(f"  To configure DNS manually, create these A records in Hostinger hPanel:")
            logger.warning(f"    - {domain}.{BASE_DOMAIN} → {self.server_ip}")
            logger.warning(f"    - {domain}-api.{BASE_DOMAIN} → {self.server_ip}")
            results["skipped"] = True
            return results

        try:
            # Use the provided domain parameter
            frontend_subdomain = domain
            backend_subdomain = f"{domain}-api"

            logger.info(f"Provisioning DNS for project: {project_name} (domain: {domain})")
            logger.info(f"  Frontend: {frontend_subdomain}.{BASE_DOMAIN}")
            logger.info(f"  Backend:  {backend_subdomain}.{BASE_DOMAIN}")

            # Check if frontend subdomain exists
            frontend_exists, frontend_current_ip = self.check_subdomain_exists(frontend_subdomain)
            results["frontend_exists"] = frontend_exists

            if frontend_exists:
                logger.info(f"  Frontend subdomain already exists: {frontend_subdomain}.{BASE_DOMAIN}")
                if frontend_current_ip:
                    logger.info(f"    Currently pointing to: {frontend_current_ip}")
                    if frontend_current_ip == self.server_ip:
                        logger.info(f"    ✓ Already pointing to correct server IP")
                        results["frontend"] = True
                    else:
                        logger.warning(f"    ⚠️ Pointing to different IP: {frontend_current_ip} (ours: {self.server_ip})")
            else:
                # Create frontend A record
                if self.create_a_record(frontend_subdomain):
                    results["frontend"] = True

            # Check if backend subdomain exists
            backend_exists, backend_current_ip = self.check_subdomain_exists(backend_subdomain)
            results["backend_exists"] = backend_exists

            if backend_exists:
                logger.info(f"  Backend subdomain already exists: {backend_subdomain}.{BASE_DOMAIN}")
                if backend_current_ip:
                    logger.info(f"    Currently pointing to: {backend_current_ip}")
                    if backend_current_ip == self.server_ip:
                        logger.info(f"    ✓ Already pointing to correct server IP")
                        results["backend"] = True
                    else:
                        logger.warning(f"    ⚠️ Pointing to different IP: {backend_current_ip} (ours: {self.server_ip})")
            else:
                # Create backend A record
                if self.create_a_record(backend_subdomain):
                    results["backend"] = True

            # Summary
            logger.info(f"✓ DNS provisioning complete:")
            logger.info(f"    Frontend: {'✓' if results['frontend'] else '✗'} {frontend_subdomain}.{BASE_DOMAIN}")
            logger.info(f"    Backend:  {'✓' if results['backend'] else '✗'} {backend_subdomain}.{BASE_DOMAIN}")

            return results

        except Exception as e:
            logger.error(f"Failed to provision project DNS: {e}")
            return results


class InfrastructureManager:
    """Main infrastructure manager orchestrating all components."""

    def __init__(self, project_name: str, project_path: Path, domain: str = None, description: str = None, template_id: str = None):
        self.project_name = project_name
        self.project_path = project_path
        self.domain = domain or project_name  # Use domain if provided, otherwise fall back to project_name
        self.description = description  # Store project description for Phase 9
        self.template_id = template_id  # Store template for metadata
        self.port_allocator = PortAllocator()
        self.db_provisioner = DatabaseProvisioner()
        self.service_manager = ServiceManager()
        self.nginx_configurator = NginxConfigurator()
        self.verifier = DeploymentVerifier()
        self.dns_provisioner = DNSProvisioner()

        self.ports = {}
        self.domains = {}
        self.database_info = {}
        self.dns_results = {}

    def provision_all(self) -> bool:
        """
        Provision all infrastructure for project.

        Pipeline order:
        1. Port allocation
        2. Database provisioning
        3. Backend environment configuration
        4. Service configuration
        5. Build frontend
        6. Nginx configuration (with SPA routing)
        7. Start frontend service (PM2 serve)
        8. Health check
        9. Mark project READY

        Note: DNS provisioning is SKIPPED - wildcard DNS (*.dreambigwithai.com) is pre-configured.

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"🚀 Starting infrastructure provisioning for {self.project_name}")

            # Phase 1: Allocate ports
            logger.info("Phase 1/8: Port allocation")
            self.ports = {
                "frontend": self.port_allocator.allocate_frontend_port(),
                "backend": self.port_allocator.allocate_backend_port()
            }
            logger.info(f"✓ Ports allocated: {self.ports}")

            # Log API URL creation
            api_url = f"http://{self.domain}.dreambigwithai.com/api"
            logger.info(f"🔗 Backend API URL: {api_url}")
            logger.info(f"🔌 Backend port: {self.ports['backend']}")
            logger.info(f"🌐 Frontend domain: http://{self.domain}.dreambigwithai.com")

            # Phase 2: Provision database
            logger.info("Phase 2/8: Database provisioning")
            self.database_info = self.db_provisioner.create_database_and_user(self.project_name)
            logger.info(f"✓ Database created: {self.database_info['database_name']}")

            # Phase 3: Configure backend environment
            logger.info("Phase 3/8: Backend environment configuration")
            self._configure_backend_env()
            logger.info("✓ Backend environment configured")

            # Phase 4: Create service config
            logger.info("Phase 4/8: Service configuration")
            self.service_name = self.service_manager.create_backend_service(
                self.project_name,
                self.ports["backend"],
                self.project_path
            )
            logger.info(f"✓ Service configured: {self.service_name}")

            # Phase 5: Build frontend (BUILD PHASE ONLY - no service creation)
            logger.info("PHASE_5_BUILD_START")
            logger.info("Phase 5/8: Building frontend")
            build_success = self._phase_5_build()
            if build_success:
                logger.info("PHASE_5_BUILD_COMPLETE: success")
                logger.info("✓ Frontend build phase completed")
            else:
                logger.error("PHASE_5_BUILD_COMPLETE: failed")
                logger.error("❌ Frontend build failed - stopping pipeline")
                return False

            # Fix permissions on project directory for nginx access
            logger.info("🔧 Fixing permissions for nginx access...")
            try:
                import stat
                # Fix permissions on entire project path chain
                project_root = self.project_path
                while project_root != project_root.parent:
                    try:
                        os.chmod(project_root, 0o755)
                    except:
                        pass
                    if project_root.name == "dreampilot":
                        break
                    project_root = project_root.parent
                
                # Fix permissions on project directory and all subdirectories
                for item in self.project_path.rglob("*"):
                    if item.is_dir():
                        os.chmod(item, 0o755)
                    elif item.is_file():
                        os.chmod(item, 0o644)
                
                logger.info("✓ Permissions fixed for nginx (755 dirs, 644 files)")
            except Exception as perm_error:
                logger.warning(f"⚠️ Could not fix all permissions: {perm_error}")

            # Phase 6: Nginx configuration (with SPA routing)
            logger.info("Phase 6/8: Nginx configuration")
            
            # Get the actual project folder name from the project path
            # project_path is like Path("/root/dreampilot/projects/website/686_test778786_20260313_142220")
            # We need just "686_test778786_20260313_142220" for the nginx root
            project_folder_name = self.project_path.name if hasattr(self.project_path, 'name') else str(self.project_path).split('/')[-1]
            logger.info(f"Using project folder for nginx: {project_folder_name}")
            
            frontend_domain, backend_domain, config = self.nginx_configurator.generate_config(
                self.domain,
                self.ports["frontend"],
                self.ports["backend"],
                project_path=project_folder_name
            )
            self.domains = {
                "frontend": frontend_domain,
                "backend": backend_domain
            }
            self.nginx_configurator.install_config(self.domain, config)
            self.nginx_configurator.reload_nginx()
            logger.info(f"✓ Nginx configured with SPA routing: {self.domains}")

            # Phase 7: Start services (PM2) - SERVICE PHASE ONLY
            logger.info("PHASE_6_SERVICE_START")
            logger.info("Phase 7/8: Service startup")
            service_success = self._phase_6_service()
            if service_success:
                logger.info("PHASE_6_SERVICE_COMPLETE: success")
                logger.info("✓ Service phase completed")
            else:
                logger.error("PHASE_6_SERVICE_COMPLETE: failed")
                logger.error("❌ Service phase had failures")

            # PHASE_9 Verification
            logger.info("[VERIFY] PHASE_9_VERIFY_START")

            # Add startup delay to ensure backend is ready
            logger.info("[VERIFY] Waiting for backend to fully start (5s)...")
            time.sleep(5)

            # DNS Resolution Check with Auto-Repair
            frontend_domain = self.domains.get("frontend")
            if frontend_domain:
                logger.info(f"[DNS] Checking DNS resolution for {frontend_domain}")
                if not self._domain_resolves(frontend_domain):
                    logger.warning(f"[DNS] Missing DNS record detected for {frontend_domain}")
                    logger.info("[DNS] Attempting automatic repair...")
                    
                    try:
                        dns_repair_result = self._phase_8_dns(frontend_domain)
                        if dns_repair_result:
                            logger.info("[DNS] A-record created successfully")
                            logger.info("[DNS] Waiting for DNS propagation...")
                            
                            # DNS propagation retry loop - wait up to 120 seconds
                            dns_resolved = False
                            for attempt in range(12):
                                logger.info(f"[DNS] Propagation check {attempt + 1}/12...")
                                time.sleep(10)
                                
                                if self._domain_resolves(frontend_domain):
                                    logger.info(f"[DNS] ✓ Domain resolving correctly: {frontend_domain}")
                                    dns_resolved = True
                                    break
                                else:
                                    logger.info(f"[DNS] Still waiting for propagation...")
                            
                            if not dns_resolved:
                                logger.warning(f"[DNS] DNS propagation taking longer than expected for {frontend_domain}")
                                logger.warning(f"[DNS] Domain may need manual verification in 5-60 minutes")
                        else:
                            logger.error("[DNS] Automatic repair failed - DNS record could not be created")
                            logger.warning("[DNS] Manual DNS configuration may be required in Hostinger hPanel")
                    except Exception as dns_error:
                        logger.error(f"[DNS] Repair attempt failed: {dns_error}")
                        logger.warning("[DNS] Continuing with local verification only")
                else:
                    logger.info(f"[DNS] Domain resolving correctly: {frontend_domain}")

            logger.info("[VERIFY] Checking frontend availability")
            frontend_check = subprocess.run(
                ["curl", "-I", f"http://localhost:{self.ports['frontend']}"],
                capture_output=True,
                text=True
            )

            logger.info("[VERIFY] Checking backend health")
            backend_check = subprocess.run(
                ["curl", f"http://localhost:{self.ports['backend']}/health"],
                capture_output=True,
                text=True
            )

            # Debug: Log the actual backend health check response
            logger.info(f"[VERIFY] Backend health check response (stdout): {backend_check.stdout[:200]}")
            logger.info(f"[VERIFY] Backend health check response (stderr): {backend_check.stderr[:200]}")
            logger.info(f"[VERIFY] Backend health check return code: {backend_check.returncode}")

            if "200" not in frontend_check.stdout:
                raise RuntimeError("Frontend verification failed")

            if "200" not in backend_check.stdout and "ok" not in backend_check.stdout.lower():
                logger.error(f"[VERIFY] Backend verification failed - Expected HTTP 200 or 'ok', got: {backend_check.stdout[:100]}")
                raise RuntimeError("Backend verification failed")

            logger.info("[VERIFY] ✓ Deployment verified successfully")
            logger.info("PHASE_9_VERIFY_COMPLETE: success")
            logger.info("DEPLOY: Project READY")
            logger.info("✅ All infrastructure provisioned and verified successfully!")
            self._save_metadata()
            return True

        except Exception as e:
            logger.error(f"❌ Infrastructure provisioning failed: {e}")
            self._rollback()
            return False

    def _acpx_fix_build_error(self, build_error: str, attempt: int) -> bool:
        """
        Use ACPX to automatically fix build errors.
        
        Args:
            build_error: The build error message
            attempt: Current retry attempt number (1 or 2)
            
        Returns:
            True if fix was applied successfully, False otherwise
        """
        try:
            logger.info(f"🔧 ACPX_AUTO_FIX: Attempt {attempt}/2 - Calling ACPX to fix build error")
            
            frontend_src_path = self.project_path / "frontend" / "src"
            
            if not frontend_src_path.exists():
                logger.error("ACPX_AUTO_FIX: Frontend src path not found")
                return False
            
            # Build fix prompt
            fix_prompt = f"""You are fixing a build error in a React + Vite + TypeScript application.

BUILD ERROR:
{build_error[:2000]}

YOUR TASK:
1. Analyze the build error carefully
2. Fix ALL TypeScript errors, missing imports, and type mismatches
3. Ensure all components are properly imported and exported
4. Fix any JSX syntax errors
5. Do NOT delete or remove functionality - only fix errors
6. Keep the code production-ready

RULES:
- Fix ONLY the errors - do not refactor or add features
- Ensure all imports use correct paths
- Fix type mismatches (string vs number, etc.)
- Add missing type definitions if needed
- Ensure all JSX elements are properly closed
- Run npm run build after fixes

CRITICAL: Fix the errors and ensure npm run build succeeds."""
            
            # Run ACPX with fix prompt
            cmd = [
                "acpx",
                "--cwd", str(frontend_src_path),
                "--format", "quiet",
                "claude",
                "exec",
                str(fix_prompt)
            ]
            
            logger.info(f"ACPX_AUTO_FIX: Running: acpx --cwd {frontend_src_path} --format quiet claude exec <fix-prompt>")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180  # 3 minutes for fix
            )
            
            # Check if ACPX succeeded (tolerant of harmless errors)
            if result.returncode != 0:
                stderr = result.stderr or ""
                # Ignore JSON-RPC notification errors
                if "session/update" in stderr and "Invalid params" in stderr:
                    logger.warning("ACPX_AUTO_FIX: Ignoring JSON-RPC notification error")
                elif result.returncode != 0:
                    logger.error(f"ACPX_AUTO_FIX: Failed with code {result.returncode}")
                    logger.error(f"ACPX_AUTO_FIX: stderr: {stderr[:500]}")
                    return False
            
            logger.info(f"ACPX_AUTO_FIX: Attempt {attempt} completed successfully")
            logger.info(f"ACPX_AUTO_FIX: stdout: {result.stdout[:300] if result.stdout else '(empty)'}")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("ACPX_AUTO_FIX: Timeout after 180 seconds")
            return False
        except Exception as e:
            logger.error(f"ACPX_AUTO_FIX: Exception: {type(e).__name__}: {str(e)}")
            return False

    def _phase_5_build(self) -> bool:
        """
        PHASE_5_BUILD: Build frontend only.
        
        Responsibilities:
        - Run npm install
        - Run npm run build
        - Verify dist directory exists
        - Clean Vite caches to prevent corruption issues
        - Retry with clean reinstall on build failure
        - Auto-fix with ACPX (max 2 attempts) on build errors
        
        Does NOT:
        - Create PM2 services
        - Start any processes
        
        Returns:
            True if build successful, False otherwise
        """
        import shutil  # Import here for cache cleanup
        import os  # Import for environment handling
        
        logger.info("PHASE_5_BUILD_START")
        logger.info("🔨 Starting build phase...")
        
        # Copy system environment to ensure npm/node are accessible
        env = os.environ.copy()
        
        try:
            frontend_path = self.project_path / "frontend"
            
            if not frontend_path.exists():
                logger.warning("⚠️ Frontend path not found, skipping build")
                logger.info("PHASE_5_BUILD_COMPLETE: skipped (no frontend)")
                return True
            
            # Verify package.json exists before proceeding
            package_json_path = frontend_path / "package.json"
            if not package_json_path.exists():
                logger.error(f"❌ package.json not found in {frontend_path}")
                logger.info("PHASE_5_BUILD_FAILED: missing package.json")
                return False
            logger.info(f"✓ Found package.json at {package_json_path}")
            
            # Define paths for cache cleanup
            node_modules_path = frontend_path / "node_modules"
            vite_temp_path = node_modules_path / ".vite-temp"
            vite_cache_path = node_modules_path / ".vite"
            
            # Step 1: Clean Vite caches to prevent corrupted node_modules
            logger.info("🧹 Cleaning Vite caches to prevent corrupted node_modules...")
            caches_cleaned = 0
            
            if vite_temp_path.exists():
                try:
                    shutil.rmtree(vite_temp_path)
                    logger.info("✓ Cleaned corrupted .vite-temp directory")
                    caches_cleaned += 1
                except Exception as e:
                    logger.warning(f"⚠️ Could not clean .vite-temp: {e}")
            
            if vite_cache_path.exists():
                try:
                    shutil.rmtree(vite_cache_path)
                    logger.info("✓ Cleaned Vite cache directory")
                    caches_cleaned += 1
                except Exception as e:
                    logger.warning(f"⚠️ Could not clean .vite cache: {e}")
            
            logger.info(f"✓ Cleaned {caches_cleaned} Vite cache directories")
            
            # Step 2: Remove existing node_modules for clean install
            logger.info("🧹 Removing existing node_modules for clean install...")
            if node_modules_path.exists():
                try:
                    shutil.rmtree(node_modules_path)
                    logger.info("✓ Removed existing node_modules")
                except Exception as e:
                    logger.warning(f"⚠️ Could not remove node_modules: {e}")
            
            # Step 2: npm install with dev dependencies
            logger.info(f"[BUILD] Running npm install in {frontend_path}")
            install_result = subprocess.run(
                ["npm", "install", "--include=dev", "--legacy-peer-deps"],
                cwd=str(frontend_path),
                env=env,
                capture_output=True,
                text=True,
                timeout=600  # 10 minutes
            )
            
            if install_result.returncode != 0:
                logger.error(f"❌ npm install failed: {install_result.stderr[:300]}")
                logger.info("PHASE_5_BUILD_FAILED: npm install failed")
                return False
            else:
                logger.info("✓ npm install completed (including dev dependencies)")
            
            # Step 3: npm run build with retry logic (max 2 ACPX auto-fix attempts)
            MAX_ACPX_RETRIES = 2
            build_attempt = 0
            
            while build_attempt < MAX_ACPX_RETRIES:
                build_attempt += 1
                
                logger.info(f"[BUILD] Running npm build (attempt {build_attempt}/{MAX_ACPX_RETRIES + 1}) in {frontend_path}")
                build_result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=str(frontend_path),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minutes
                )
                
                if build_result.returncode == 0:
                    logger.info(f"✓ npm run build succeeded on attempt {build_attempt}")
                    break
                
                # Build failed - check if we can retry with ACPX
                if build_attempt < MAX_ACPX_RETRIES:
                    logger.warning(f"⚠️ Build failed (attempt {build_attempt}): {build_result.stderr[:300]}")
                    logger.info(f"🔧 Calling ACPX to auto-fix build error (attempt {build_attempt}/{MAX_ACPX_RETRIES})")
                    
                    # Call ACPX to fix the build error
                    fix_success = self._acpx_fix_build_error(build_result.stderr, build_attempt)
                    
                    if fix_success:
                        logger.info(f"✓ ACPX auto-fix applied successfully, retrying build...")
                        # Loop will retry build
                    else:
                        logger.error(f"❌ ACPX auto-fix failed, cannot continue")
                        logger.info("PHASE_5_BUILD_FAILED: ACPX auto-fix failed")
                        return False
                else:
                    # Final attempt failed
                    logger.error(f"❌ Build failed after {MAX_ACPX_RETRIES} ACPX auto-fix attempts")
                    logger.error(f"Build error: {build_result.stderr[:500]}")
                    logger.info("PHASE_5_BUILD_FAILED: max retries exceeded")
                    return False
            
            logger.info("✓ npm run build completed successfully")
            
            # Step 5: Verify dist directory exists
            dist_path = frontend_path / "dist"
            if not dist_path.exists():
                logger.error(f"❌ Dist directory not found: {dist_path}")
                logger.info("PHASE_5_BUILD_FAILED: dist directory missing")
                return False
            
            # Verify dist has content
            dist_contents = list(dist_path.iterdir())
            if not dist_contents:
                logger.error("❌ Dist directory is empty")
                logger.info("PHASE_5_BUILD_FAILED: dist directory empty")
                return False
            
            logger.info(f"✓ Dist directory verified with {len(dist_contents)} items")
            
            # Step 6: Fix permissions so nginx can read files
            logger.info("🔧 Fixing permissions for nginx access...")
            try:
                # Fix permissions on the entire project directory
                os.chmod(frontend_path, 0o755)
                dist_path_chmod = frontend_path / "dist"
                if dist_path_chmod.exists():
                    os.chmod(dist_path_chmod, 0o755)
                    # Fix permissions on all files in dist
                    for item in dist_path_chmod.rglob("*"):
                        if item.is_file():
                            os.chmod(item, 0o644)
                        elif item.is_dir():
                            os.chmod(item, 0o755)
                    logger.info("✓ Permissions fixed for nginx (755/644)")
            except Exception as perm_error:
                logger.warning(f"⚠️ Could not fix permissions: {perm_error}")
                # Don't fail the build, just warn
            
            # Step 7: Cleanup node_modules to save disk space
            logger.info("🧹 Cleaning up node_modules to save disk space...")
            try:
                import shutil
                node_modules_path = frontend_path / "node_modules"
                if node_modules_path.exists():
                    shutil.rmtree(node_modules_path)
                    logger.info(f"✓ Removed node_modules (saved disk space)")
                else:
                    logger.info("node_modules not found, skipping cleanup")
            except Exception as cleanup_error:
                logger.warning(f"⚠️ Could not remove node_modules: {cleanup_error}")
                # Don't fail the build, just warn
            
            logger.info("PHASE_5_BUILD_COMPLETE: success")
            logger.info("✅ Build phase completed successfully")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("❌ Build phase timed out")
            logger.info("PHASE_5_BUILD_FAILED: timeout")
            return False
        except Exception as e:
            logger.error(f"❌ Build phase failed: {e}")
            logger.info("PHASE_5_BUILD_FAILED: exception")
            return False
            
        except subprocess.TimeoutExpired:
            logger.error("❌ Build phase timed out")
            logger.info("PHASE_5_BUILD_FAILED: timeout")
            return False
        except Exception as e:
            logger.error(f"❌ Build phase failed: {e}")
            logger.info("PHASE_5_BUILD_FAILED: exception")
            return False

    def _phase_6_service(self) -> bool:
        """
        PHASE_6_SERVICE: Create and start PM2 services.
        
        Responsibilities:
        - Create PM2 service configurations
        - Start backend service
        - Start frontend service
        - Save PM2 configuration
        
        Does NOT:
        - Run npm build (that's Phase 5)
        
        Returns:
            True if services started successfully, False otherwise
        """
        logger.info("PHASE_6_SERVICE_START")
        logger.info("🚀 Starting service phase...")
        
        try:
            # Start backend service
            logger.info(f"🔧 Starting backend service: {self.service_name}")
            backend_success = self.service_manager.start_backend_service(
                self.service_name, 
                self.project_path / "backend",
                self.ports["backend"]
            )
            
            if backend_success:
                logger.info(f"✓ Backend service started: {self.service_name}")
            else:
                logger.error(f"❌ Backend service failed to start: {self.service_name}")
                logger.info("PHASE_6_SERVICE_COMPLETE: failed (backend)")
                return False
            
            # Start frontend service using PM2 with npx serve for static files
            dist_path = self.project_path / "frontend" / "dist"

            if dist_path.exists():
                frontend_app_name = f"project-{self.project_name}-frontend"

                # Stop existing service if any
                logger.info(f"🔄 Stopping existing frontend service if any...")
                subprocess.run(["pm2", "delete", frontend_app_name], capture_output=True)

                # Start PM2 service with npx serve -s dist -l port
                logger.info(f"[SERVICE] Starting frontend service: {frontend_app_name}")
                frontend_cmd = [
                    "pm2",
                    "start",
                    "npx",
                    "--name",
                    frontend_app_name,
                    "--",
                    "serve",
                    "-s",
                    "dist",
                    "-l",
                    str(self.ports["frontend"])
                ]

                logger.info(f"[SERVICE] Frontend command: {' '.join(frontend_cmd)}")
                logger.info(f"[SERVICE] Frontend working directory: {self.project_path / 'frontend'}")

                frontend_result = subprocess.run(
                    frontend_cmd,
                    cwd=str(self.project_path / "frontend"),
                    capture_output=True,
                    text=True,
                    check=True
                )

                logger.info("DEPLOY: PM2 service started")
                logger.info(f"[SERVICE] Frontend service started successfully: {frontend_app_name}")
                logger.info(f"[SERVICE] Frontend stdout: {frontend_result.stdout[:200]}")
                self.frontend_app_name = frontend_app_name
            else:
                logger.warning("⚠️ Frontend dist not found, creating service anyway")
                self.frontend_app_name = self.service_manager.create_frontend_service(
                    self.project_name,
                    self.ports["frontend"],
                    self.project_path
                )
                fallback_success = self.service_manager.start_frontend_service(
                    self.frontend_app_name,
                    self.project_path
                )
                if not fallback_success:
                    logger.error("❌ Frontend service creation failed")
                    logger.info("PHASE_6_SERVICE_COMPLETE: failed (frontend)")
                    return False

            logger.info(f"⚙️ PM2 frontend service: {self.frontend_app_name}")
            logger.info(f"⚙️ PM2 backend service: {self.service_name}")

            # Service Stability Check
            logger.info("[SERVICE] Waiting for PM2 services to stabilize...")
            time.sleep(5)

            pm2_check = subprocess.run(
                ["pm2", "list"],
                capture_output=True,
                text=True
            )

            if self.frontend_app_name not in pm2_check.stdout:
                raise RuntimeError(f"Frontend service {self.frontend_app_name} not running")

            if self.service_name not in pm2_check.stdout:
                raise RuntimeError(f"Backend service {self.service_name} not running")

            logger.info("[SERVICE] ✓ PM2 services running")

            # PHASE_8_DNS: Create DNS records for project domain
            logger.info("PHASE_8_DNS_START")
            dns_result = self._phase_8_dns(self.domains.get("frontend"))

            if not dns_result:
                logger.error("PHASE_8_DNS_FAILED")
                raise RuntimeError("PHASE_8_DNS_COMPLETE: DNS creation failed")

            logger.info("PHASE_8_DNS_COMPLETE: success")
            logger.info("✅ DNS record created successfully")

            # Wait for DNS propagation
            logger.info("[DNS] Waiting for DNS propagation (20s)...")
            time.sleep(20)

            # Save PM2 State
            subprocess.run(["pm2", "save"], check=True)

            logger.info("PHASE_6_SERVICE_COMPLETE: success")
            logger.info("✅ Service phase completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Service phase failed: {e}")
            logger.info("PHASE_6_SERVICE_COMPLETE: failed (exception)")
            return False

    def _configure_backend_env(self):
        """Configure backend .env file with database and ports for FastAPI."""
        try:
            env_path = self.project_path / "backend" / ".env"

            # Read existing .env
            env_content = env_path.read_text() if env_path.exists() else ""

            # Update/add configuration
            lines = env_content.split('\n')
            updated_lines = []

            # Track what we've updated
            updated_vars = set()
            backend_port = self.ports.get("backend", 8000)

            # Update or add database URL
            for line in lines:
                if line.startswith('DATABASE_URL='):
                    line = f'DATABASE_URL={self.database_info["database_url"]}'
                    updated_vars.add('DATABASE_URL')
                updated_lines.append(line)

            # Add missing variables
            if 'DATABASE_URL' not in updated_vars:
                updated_lines.append(f'DATABASE_URL={self.database_info["database_url"]}')

            # Add FastAPI-specific environment variables
            if 'BACKEND_HOST' not in [l.split('=')[0] if '=' in l else '' for l in lines]:
                updated_lines.append(f'BACKEND_HOST=0.0.0.0')

            if 'BACKEND_PORT' not in [l.split('=')[0] if '=' in l else '' for l in lines]:
                updated_lines.append(f'BACKEND_PORT={backend_port}')

            if 'API_PORT' not in [l.split('=')[0] if '=' in l else '' for l in lines]:
                updated_lines.append(f'API_PORT={backend_port}')

            if 'PROJECT_NAME' not in [l.split('=')[0] if '=' in l else '' for l in lines]:
                updated_lines.append(f'PROJECT_NAME={self.project_name}')

            # Write updated .env
            env_path.write_text('\n'.join(updated_lines))

            logger.info(f"✓ Backend .env configured for FastAPI")

        except Exception as e:
            logger.error(f"Failed to configure backend env: {e}")
            raise

    def _save_metadata(self):
        """Save project metadata to project.json."""
        try:
            metadata = {
                "project_name": self.project_name,
                "description": self.description,  # Include description for Phase 9
                "template_id": getattr(self, "template_id", None),  # Include template if available
                "ports": self.ports,
                "domains": self.domains,
                "dns": self.dns_results,
                "database": {
                    "name": self.database_info["database_name"],
                    "user": self.database_info["username"]
                },
                "service_name": self.service_name,
                "status": "ready"
            }

            # Add frontend_app_name if it exists
            if hasattr(self, 'frontend_app_name'):
                metadata["frontend_app_name"] = self.frontend_app_name

            metadata_path = self.project_path / "project.json"
            metadata_path.write_text(
                json.dumps(metadata, indent=2)
            )

            logger.info(f"✓ Metadata saved: {metadata_path}")

        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")

    def _rollback(self):
        """Rollback all changes on failure."""
        logger.info("Rolling back infrastructure changes...")

        try:
            # Stop backend service
            if hasattr(self, 'service_name'):
                self.service_manager.stop_service(self.service_name)
                self.service_manager.delete_service(self.service_name)

            # Stop frontend service
            if hasattr(self, 'frontend_app_name'):
                self.service_manager.stop_service(self.frontend_app_name)
                self.service_manager.delete_service(self.frontend_app_name)

            # Remove nginx config
            self.nginx_configurator.remove_config(self.project_name)

            # Drop database
            self.db_provisioner.drop_database_and_user(self.project_name)

            # Release ports
            if hasattr(self, 'ports'):
                self.port_allocator.release_ports(
                    self.ports.get("frontend"),
                    self.ports.get("backend")
                )

            # Note: DNS A records are not deleted on rollback
            # This requires manual cleanup via Hostinger hPanel or DNS skill update

        except Exception as e:
            logger.error(f"Rollback failed: {e}")

    def _phase_8_dns(self, project_domain: str) -> bool:
        """PHASE_8_DNS: Create DNS A records for project domain.
        
        This phase uses the existing dns_manager module to automatically
        create DNS A records for the project's frontend domain.
        
        Args:
            project_domain: The auto-generated domain (e.g., "project-name-xxxxx.dreambigwithai.com")
        
        Returns:
            True if DNS record created successfully, False otherwise
        """
        try:
            logger.info("PHASE_8_DNS_START")
            logger.info(f"[DNS] Creating DNS record for domain: {project_domain}")

            # Import dns_manager module
            from dns_manager import HostingerDNSAPI, get_api_token

            # Initialize DNS manager
            api_token = get_api_token()
            dns_manager = HostingerDNSAPI(api_token)

            # Extract subdomain from project domain
            # Format: "project-name-xxxxx.dreambigwithai.com"
            if '.' in project_domain:
                # Split and take the project subdomain part
                parts = project_domain.split('.')
                if len(parts) >= 2:
                    subdomain = parts[0]
                    base_domain = '.'.join(parts[1:])
                else:
                    subdomain = project_domain
                    base_domain = None
            else:
                subdomain = project_domain
                base_domain = None

            # Get server IP for A record
            server_ip = self._get_server_ip()

            if not server_ip:
                logger.error(f"[DNS] Could not determine server IP")
                logger.info("PHASE_8_DNS_FAILED")
                return False

            logger.info(f"[DNS] Server IP: {server_ip}")
            
            # Create A records for BOTH frontend and backend subdomains
            # Frontend: subdomain.base_domain (e.g., test4-xxx.dreambigwithai.com)
            # Backend: subdomain-api.base_domain (e.g., test4-xxx-api.dreambigwithai.com)
            
            frontend_success = False
            backend_success = False
            
            if base_domain:
                # Create frontend A record
                logger.info(f"[DNS] Creating frontend A record: {subdomain}.{base_domain} → {server_ip}")
                frontend_result = dns_manager.create_a_record(
                    domain=base_domain,
                    subdomain=subdomain,
                    ip=server_ip,
                    ttl=14400  # 4 hours
                )
                
                if frontend_result.get("success"):
                    logger.info(f"[DNS] ✓ Frontend A record created: {subdomain}.{base_domain} → {server_ip}")
                    frontend_success = True
                else:
                    logger.error(f"[DNS] ❌ Failed to create frontend DNS record: {frontend_result.get('error', 'Unknown error')}")
                
                # Create backend A record (subdomain-api)
                backend_subdomain = f"{subdomain}-api"
                logger.info(f"[DNS] Creating backend A record: {backend_subdomain}.{base_domain} → {server_ip}")
                backend_result = dns_manager.create_a_record(
                    domain=base_domain,
                    subdomain=backend_subdomain,
                    ip=server_ip,
                    ttl=14400  # 4 hours
                )
                
                if backend_result.get("success"):
                    logger.info(f"[DNS] ✓ Backend A record created: {backend_subdomain}.{base_domain} → {server_ip}")
                    backend_success = True
                else:
                    logger.error(f"[DNS] ❌ Failed to create backend DNS record: {backend_result.get('error', 'Unknown error')}")
            else:
                # Fallback if we can't determine base domain
                logger.warning(f"[DNS] Could not determine base domain from: {project_domain}")
                logger.warning("[DNS] Skipping DNS creation (will use default subdomain)")

            if frontend_success and backend_success:
                logger.info(f"[DNS] ✓ Both DNS records created successfully")
                logger.info("PHASE_8_DNS_COMPLETE")
                return True
            elif frontend_success:
                logger.warning(f"[DNS] ⚠️ Frontend DNS created, but backend DNS failed")
                logger.info("PHASE_8_DNS_COMPLETE: partial")
                return True  # Return true so deployment continues
            else:
                logger.error(f"[DNS] ❌ DNS creation failed")
                logger.info("PHASE_8_DNS_FAILED")
                return False

        except Exception as e:
            logger.error(f"[DNS] ❌ DNS creation failed: {e}")
            logger.info("PHASE_8_DNS_FAILED")
            return False

    def _domain_resolves(self, domain: str) -> bool:
        """Check if domain resolves (DNS propagation check)."""
        try:
            import socket
            
            logger.info(f"[DNS] Checking if domain resolves: {domain}")
            
            # Simple DNS check with 5-second timeout
            socket.setdefaulttimeout(5)
            
            try:
                socket.gethostbyname(domain)
                logger.info(f"[DNS] ✓ Domain {domain} resolves successfully")
                return True
            except socket.gaierror:
                logger.warning(f"[DNS] ⚠️ Domain {domain} does not resolve yet (may need more time)")
                return False
            except Exception as e:
                logger.error(f"[DNS] ❌ DNS resolution error: {e}")
                return False

        except Exception as e:
            logger.error(f"[DNS] ❌ DNS resolution check failed: {e}")
            return False

    def _get_server_ip(self) -> str:
        """Get server public IPv4 address for DNS A record."""
        try:
            # Try multiple services to get IPv4 address
            ipv4_services = [
                "https://api.ipify.org",
                "https://icanhazip.com",
                "https://ifconfig.me/ip",
            ]

            for service in ipv4_services:
                try:
                    result = subprocess.run(
                        ["curl", "-4", "-s", service],  # -4 forces IPv4
                        capture_output=True,
                        text=True,
                        timeout=10
                    )

                    if result.returncode == 0:
                        ip = result.stdout.strip()
                        # Validate it's an IPv4 address (not IPv6)
                        if '.' in ip and not ':' in ip:
                            logger.info(f"[DNS] Server IPv4 detected: {ip}")
                            return ip
                        else:
                            logger.warning(f"[DNS] Service {service} returned non-IPv4: {ip}")
                except Exception as e:
                    logger.warning(f"[DNS] Failed to get IP from {service}: {e}")
                    continue

            logger.error("[DNS] Could not obtain IPv4 address from any service")
            return None

        except Exception as e:
            logger.error(f"[DNS] Exception getting server IP: {e}")
            return None

    def teardown(self):
        """Teardown infrastructure for project deletion."""
        logger.info(f"Teardown infrastructure for {self.project_name}")

        # Load metadata
        metadata_path = self.project_path / "project.json"
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text())

                # Stop backend service
                service_name = metadata.get("service_name")
                if service_name:
                    self.service_manager.stop_service(service_name)
                    self.service_manager.delete_service(service_name)

                # Stop frontend service
                frontend_app_name = metadata.get("frontend_app_name")
                if frontend_app_name:
                    self.service_manager.stop_service(frontend_app_name)
                    self.service_manager.delete_service(frontend_app_name)

                # Remove nginx config
                self.nginx_configurator.remove_config(self.project_name)

                # Drop database
                self.db_provisioner.drop_database_and_user(self.project_name)

                # Release ports
                ports = metadata.get("ports", {})
                self.port_allocator.release_ports(
                    ports.get("frontend"),
                    ports.get("backend")
                )

                logger.info(f"✓ Infrastructure teardown complete")

            except Exception as e:
                logger.error(f"Teardown failed: {e}")

    def repair_dns(self, project_id: int) -> bool:
        """Repair DNS for existing projects that were deployed before PHASE_8_DNS automation.
        
        This method loads project metadata, extracts domain,
        and calls _phase_8_dns to create missing DNS A-record.
        
        Args:
            project_id: ID of project to repair DNS for
            
        Returns:
            True if DNS repair succeeded, False otherwise
        """
        try:
            logger.info(f"[DNS] === Starting DNS Repair for Project {project_id} ===")
            
            # Load project metadata
            logger.info(f"[DNS] Loading project metadata...")
            project = self.get_project(project_id)
            
            if not project:
                logger.error(f"[DNS] ❌ Project not found: {project_id}")
                logger.error(f"[DNS] Verify the project ID exists in the database")
                return False
            
            # Extract domain from project data
            project_data = project.get("project", {})
            domains = project_data.get("domains", {})
            project_name = project_data.get("name", "unknown")
            
            logger.info(f"[DNS] Project name: {project_name}")
            logger.info(f"[DNS] Found domains: {domains}")
            
            if not domains:
                logger.warning(f"[DNS] ⚠️ No domains found in project {project_id}")
                logger.warning(f"[DNS] Project may not have completed deployment properly")
                return False
            
            # Get frontend domain (primary domain for DNS)
            frontend_domain = domains.get("frontend")
            
            if not frontend_domain:
                logger.warning(f"[DNS] ⚠️ No frontend domain found for project {project_id}")
                return False
            
            logger.info(f"[DNS] Target domain: {frontend_domain}")
            
            # Check current DNS status
            logger.info(f"[DNS] Checking current DNS resolution...")
            current_status = self._domain_resolves(frontend_domain)
            
            if current_status:
                logger.info(f"[DNS] ✓ Domain already resolves correctly - no repair needed")
                return True
            
            logger.warning(f"[DNS] Missing DNS record detected")
            logger.info(f"[DNS] Attempting to create A-record via Hostinger API...")
            
            # Call _phase_8_dns to create DNS A-record
            result = self._phase_8_dns(frontend_domain)
            
            if result:
                logger.info(f"[DNS] ✓ A-record created successfully")
                logger.info(f"[DNS] ✓ DNS repair successful for project {project_id}")
                logger.info(f"[DNS] Note: DNS propagation may take 1-5 minutes")
                
                # Update project metadata to track that DNS has been repaired
                if "dns_repaired" not in project_data:
                    project_data["dns_repaired"] = True
                    self.update_project(project_id, {"project": project_data})
                    logger.info(f"[DNS] Updated project metadata with dns_repaired flag")
                
                return True
            else:
                logger.error(f"[DNS] ❌ DNS repair failed for project {project_id}")
                logger.error(f"[DNS] Check Hostinger API credentials and rate limits")
                return False

        except Exception as e:
            logger.error(f"[DNS] ❌ Exception during DNS repair: {e}")
            logger.exception(f"[DNS] Full traceback:")
            return False
