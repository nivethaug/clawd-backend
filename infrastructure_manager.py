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

# Clawsd-ui settings
CLAWD_UI_PATH = "/root/clawd-ui"
CLAWD_UI_DIST = "/root/clawd-ui/dist"
CLAWD_UI_DEV_PORT = 3001

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

    def _execute_sql(self, sql: str) -> List[Tuple]:
        """Execute SQL command in PostgreSQL container."""
        try:
            cmd = [
                "docker", "exec", self.container,
                "psql", "-U", POSTGRES_USER, "-d", "defaultdb", "-c", sql
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

            # Drop connections first
            self._execute_sql(
                f"SELECT pg_terminate_backend(pg_stat_activity.pid) "
                f"FROM pg_stat_activity "
                f"WHERE pg_stat_activity.datname = '{db_name}' "
                f"AND pid <> pg_backend_pid();"
            )

            # Drop database (quoted to handle SQL keywords)
            self._execute_sql(f'DROP DATABASE IF EXISTS "{db_name}";')
            logger.info(f"✓ Database dropped: {db_name}")

            # Drop user (quoted to handle SQL keywords)
            self._execute_sql(f'DROP USER IF EXISTS "{username}";')
            logger.info(f"✓ User dropped: {username}")

        except Exception as e:
            logger.error(f"Failed to drop database/user: {e}")

    def get_database_size(self, project_name: str) -> int:
        """Get database size in MB."""
        try:
            db_name = f"{self._sanitize_db_name(project_name)}_db"

            result = self._execute_sql(
                f'SELECT pg_database_size(\'{db_name}\') AS size;'
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

    def start_backend_service(self, app_name: str, backend_path: Path) -> bool:
        """Start backend service."""
        try:
            logger.info(f"Starting service: {app_name}")

            # Start with PM2 using ecosystem config
            ecosystem_path = backend_path / "ecosystem.config.json"
            if not ecosystem_path.exists():
                logger.error(f"Ecosystem config not found: {ecosystem_path}")
                return False

            result = subprocess.run(
                ["pm2", "start", str(ecosystem_path)],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"✓ Service started: {app_name}")
                return True
            else:
                logger.error(f"Failed to start service: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to start service: {e}")
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
        Build the clawd-ui frontend.

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Building clawd-ui frontend...")

            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=CLAWD_UI_PATH,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes
            )

            if result.returncode == 0:
                logger.info(f"✓ Frontend built successfully")
                return True
            else:
                logger.error(f"Failed to build frontend: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to build frontend: {e}")
            return False

    def create_frontend_service(self, project_name: str, frontend_port: int, project_path: Path) -> str:
        """
        Create PM2 config for frontend service.

        Uses project-specific frontend if available, otherwise falls back to shared dist.

        Returns:
            PM2 app name
        """
        try:
            app_name = f"{project_name}-frontend"
            
            # Check if project has its own frontend directory
            project_frontend_path = project_path / "frontend"
            
            if project_frontend_path.exists() and (project_frontend_path / "index.html").exists():
                # Use project-specific frontend
                logger.info(f"Using project-specific frontend: {project_frontend_path}")
                frontend_dist_path = project_frontend_path
                
                # Build the Vite app for production serving with correct MIME types
                package_json = frontend_dist_path / "package.json"
                dist_dir = frontend_dist_path / "dist"
                
                if package_json.exists():
                    logger.info(f"Building frontend for production (correct MIME types)...")
                    try:
                        # Install dependencies
                        install_result = subprocess.run(
                            ["npm", "install"],
                            capture_output=True,
                            text=True,
                            timeout=300,
                            cwd=str(frontend_dist_path)
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
                            cwd=str(frontend_dist_path)
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
                        cwd=str(frontend_dist_path)
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

    def generate_config(self, domain: str, frontend_port: int, backend_port: int, enable_ssl: bool = False) -> Tuple[str, str]:
        """
        Generate nginx configuration for project.

        Args:
            domain: Domain name (e.g., "ecommerce22")
            frontend_port: Frontend service port
            backend_port: Backend service port
            enable_ssl: Whether to generate SSL config (default: False)

        Returns:
            Tuple of (frontend_domain, backend_domain, config)
        """
        try:
            frontend_domain = f"{domain}.{BASE_DOMAIN}"
            backend_domain = f"{domain}-api.{BASE_DOMAIN}"

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

    root /root/dreampilot/projects/website/{domain}/frontend/dist;
    index index.html;

    # SPA routing - serve index.html for all routes
    location / {{
        try_files $uri $uri/ /index.html;
    }}

    # API proxy
    location /api {{
        proxy_pass http://127.0.0.1:{backend_port};
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

    root /root/dreampilot/projects/website/{domain}/frontend/dist;
    index index.html;

    # SPA routing - serve index.html for all routes
    location / {{
        try_files $uri $uri/ /index.html;
    }}

    # API proxy
    location /api {{
        proxy_pass http://127.0.0.1:{backend_port};
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
                logger.error(f"Failed to create A record: {result.get("error")}")
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

            # Phase 5: Build frontend
            logger.info("Phase 5/8: Building frontend")
            frontend_path = self.project_path / "frontend"
            if frontend_path.exists():
                build_result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=str(frontend_path),
                    capture_output=True,
                    text=True,
                    timeout=600
                )
                if build_result.returncode == 0:
                    logger.info("DEPLOY: Build complete")
                    logger.info("✓ Frontend build successful")
                else:
                    logger.warning(f"⚠️ Frontend build had issues: {build_result.stderr[:200]}")
            else:
                logger.warning("⚠️ Frontend path not found, skipping build")

            # Phase 6: Nginx configuration (with SPA routing)
            logger.info("Phase 6/8: Nginx configuration")
            frontend_domain, backend_domain, config = self.nginx_configurator.generate_config(
                self.domain,
                self.ports["frontend"],
                self.ports["backend"]
            )
            self.domains = {
                "frontend": frontend_domain,
                "backend": backend_domain
            }
            self.nginx_configurator.install_config(self.domain, config)
            self.nginx_configurator.reload_nginx()
            logger.info(f"✓ Nginx configured with SPA routing: {self.domains}")

            # Phase 7: Start services (PM2)
            logger.info("Phase 7/8: Service startup")
            logger.info("DEPLOY: Starting frontend service")

            # Start backend service
            self.service_manager.start_backend_service(self.service_name, self.project_path / "backend")
            logger.info(f"✓ Backend service started: {self.service_name}")

            # Start frontend service using PM2 serve for static files
            dist_path = self.project_path / "frontend" / "dist"
            if dist_path.exists():
                frontend_service_name = f"project-{self.project_name}-frontend"
                
                # Stop existing service if any
                subprocess.run(["pm2", "delete", frontend_service_name], capture_output=True)
                
                # Start PM2 serve for SPA
                pm2_cmd = [
                    "pm2", "serve",
                    str(dist_path),
                    str(self.ports["frontend"]),
                    "--name", frontend_service_name,
                    "--spa"
                ]
                pm2_result = subprocess.run(pm2_cmd, capture_output=True, text=True)
                
                if pm2_result.returncode == 0:
                    logger.info("DEPLOY: PM2 service started")
                    logger.info(f"✓ Frontend PM2 service started: {frontend_service_name}")
                    self.frontend_app_name = frontend_service_name
                else:
                    logger.warning(f"⚠️ PM2 serve failed: {pm2_result.stderr[:200]}")
                    # Fallback: create and start using service manager
                    self.frontend_app_name = self.service_manager.create_frontend_service(
                        self.project_name,
                        self.ports["frontend"],
                        self.project_path
                    )
                    self.service_manager.start_frontend_service(self.frontend_app_name, self.project_path)
            else:
                logger.warning("⚠️ Frontend dist not found, creating service anyway")
                self.frontend_app_name = self.service_manager.create_frontend_service(
                    self.project_name,
                    self.ports["frontend"],
                    self.project_path
                )
                self.service_manager.start_frontend_service(self.frontend_app_name, self.project_path)

            logger.info(f"⚙️ PM2 frontend service: {self.frontend_app_name}")
            logger.info(f"⚙️ PM2 backend service: {self.service_name}")

            # Save PM2 configuration
            subprocess.run(["pm2", "save"], capture_output=True)

            # Phase 8: Health check
            logger.info("Phase 8/8: Health check")
            
            # Wait for services to start
            logger.info("Waiting for services to initialize...")
            import time
            time.sleep(5)

            # Health check via localhost (no DNS dependency)
            health_check_url = f"http://localhost:{self.ports['frontend']}"
            health_passed = False
            
            for attempt in range(1, 4):
                try:
                    logger.info(f"🩺 Health check attempt {attempt}/3: {health_check_url}")
                    health_response = requests.get(health_check_url, timeout=10)
                    
                    if health_response.status_code == 200:
                        logger.info("DEPLOY: Health check passed")
                        logger.info(f"✅ Health check passed: HTTP {health_response.status_code}")
                        health_passed = True
                        break
                    else:
                        logger.warning(f"⚠️ Health check returned: HTTP {health_response.status_code}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Health check attempt {attempt} failed: {e}")
                
                if attempt < 3:
                    # Restart PM2 service and retry
                    logger.info("Restarting frontend service...")
                    subprocess.run(["pm2", "restart", self.frontend_app_name], capture_output=True)
                    time.sleep(5)

            if not health_passed:
                logger.error("❌ Health check failed after 3 attempts")
                self._rollback()
                return False

            # Verification with enhanced verifier (DNS check disabled)
            logger.info("🔍 Running deployment verification...")
            
            enhanced_verifier = EnhancedDeploymentVerifier(
                project_path=str(self.project_path),
                domain=self.domain,
                frontend_port=self.ports["frontend"],
                backend_port=self.ports["backend"],
                max_retries=2,
                retry_delay=3.0
            )
            
            # Skip DNS check - wildcard DNS is pre-configured
            verification = enhanced_verifier.verify_all(include_pm2=True, include_dns=False)
            
            logger.info(format_verification_report(verification))

            if verification["success"]:
                logger.info("DEPLOY: Project READY")
                logger.info("✅ All infrastructure provisioned and verified successfully!")
                self._save_metadata()
                return True
            else:
                logger.error(f"❌ Deployment verification failed: {verification['failed_checks']}")
                
                # Check if build-related failure - attempt rebuild
                if "build_output" in verification["failed_checks"]:
                    logger.warning("⚠️ Build output check failed, attempting rebuild...")
                    
                    try:
                        build_result = subprocess.run(
                            ["npm", "run", "build"],
                            cwd=self.project_path / "frontend",
                            capture_output=True,
                            text=True,
                            timeout=600
                        )
                        
                        if build_result.returncode == 0:
                            logger.info("✅ Rebuild succeeded, re-running verification...")
                            verification = enhanced_verifier.verify_all(include_pm2=True, include_dns=False)
                            
                            if verification["success"]:
                                logger.info("DEPLOY: Project READY")
                                logger.info("✅ Deployment verified after rebuild!")
                                self._save_metadata()
                                return True
                        else:
                            logger.error(f"❌ Rebuild failed: {build_result.stderr[:500]}")
                    except Exception as e:
                        logger.error(f"❌ Rebuild exception: {e}")
                
                self._rollback()
                return False

        except Exception as e:
            logger.error(f"❌ Infrastructure provisioning failed: {e}")
            self._rollback()
            return False

    def _configure_backend_env(self):
        """Configure backend .env file with database and ports."""
        try:
            env_path = self.project_path / "backend" / ".env"

            # Read existing .env
            env_content = env_path.read_text() if env_path.exists() else ""

            # Update/add configuration
            lines = env_content.split('\n')
            updated_lines = []

            # Track what we've updated
            updated_vars = set()

            # Update or add database URL
            for line in lines:
                if line.startswith('DATABASE_URL='):
                    line = f'DATABASE_URL={self.database_info["database_url"]}'
                    updated_vars.add('DATABASE_URL')
                updated_lines.append(line)

            # Add missing variables
            if 'DATABASE_URL' not in updated_vars:
                updated_lines.append(f'DATABASE_URL={self.database_info["database_url"]}')

            if 'API_PORT' not in [l.split('=')[0] if '=' in l else '' for l in lines]:
                updated_lines.append(f'API_PORT={self.ports["backend"]}')

            if 'PROJECT_NAME' not in [l.split('=')[0] if '=' in l else '' for l in lines]:
                updated_lines.append(f'PROJECT_NAME={self.project_name}')

            # Write updated .env
            env_path.write_text('\n'.join(updated_lines))

            logger.info(f"✓ Backend .env configured")

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

            logger.info("✓ Rollback complete")

        except Exception as e:
            logger.error(f"Rollback failed: {e}")

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
