"""
Infrastructure Manager for DreamPilot

Handles all infrastructure provisioning for website projects:
- PostgreSQL database/user creation
- Port allocation
- Service management
- Nginx configuration
- Deployment verification
"""

import subprocess
import sqlite3
import random
import string
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple

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
SHARED_VENV_PATH = "/root/dreampilotvenv"


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
                logger.info(f"Loaded {len(self.used_ports)} used ports")
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Could not load used ports: {e}")

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
            db_name = f"{project_name}_db"
            username = f"{project_name}_user"
            password = self._generate_password()

            logger.info(f"Creating database: {db_name}")
            logger.info(f"Creating user: {username}")

            # Create database
            self._execute_sql(f"CREATE DATABASE {db_name};")
            logger.info(f"✓ Database created: {db_name}")

            # Create user
            self._execute_sql(
                f"CREATE USER {username} WITH PASSWORD '{password}';"
            )
            logger.info(f"✓ User created: {username}")

            # Grant privileges
            self._execute_sql(
                f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {username};"
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
            db_name = f"{project_name}_db"
            username = f"{project_name}_user"

            logger.info(f"Dropping database: {db_name}")

            # Drop connections first
            self._execute_sql(
                f"SELECT pg_terminate_backend(pg_stat_activity.pid) "
                f"FROM pg_stat_activity "
                f"WHERE pg_stat_activity.datname = '{db_name}' "
                f"AND pid <> pg_backend_pid();"
            )

            # Drop database
            self._execute_sql(f"DROP DATABASE IF EXISTS {db_name};")
            logger.info(f"✓ Database dropped: {db_name}")

            # Drop user
            self._execute_sql(f"DROP USER IF EXISTS {username};")
            logger.info(f"✓ User dropped: {username}")

        except Exception as e:
            logger.error(f"Failed to drop database/user: {e}")

    def get_database_size(self, project_name: str) -> int:
        """Get database size in MB."""
        try:
            db_name = f"{project_name}_db"

            result = self._execute_sql(
                f"SELECT pg_database_size('{db_name}') AS size;"
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
    "BACKEND_PORT": "{backend_port}",
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

        Returns:
            PM2 app name
        """
        try:
            app_name = f"{project_name}-frontend"
            frontend_dist_path = Path(CLAWD_UI_DIST)

            # Check if dist exists
            if not frontend_dist_path.exists():
                raise FileNotFoundError(f"Frontend dist directory not found: {frontend_dist_path}")

            # Create serve.py if it doesn't exist
            serve_py = frontend_dist_path / "serve.py"
            if not serve_py.exists():
                serve_script = """#!/usr/bin/env python3
import http.server
import socketserver
import os
from urllib.parse import unquote

class CORSHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_GET(self):
        # Serve index.html for SPA routing
        if self.path != '/' and not self.path.startswith('/assets') and '.' not in self.path.split('?')[0]:
            self.path = '/index.html'
        return super().do_GET()

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 3000))
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    with socketserver.TCPServer(("", PORT), CORSHTTPRequestHandler) as httpd:
        print(f"Serving on port {PORT}...")
        httpd.serve_forever()
"""
                serve_py.write_text(serve_script)

            # PM2 ecosystem config
            ecosystem = f"""{{
  "name": "{app_name}",
  "script": "serve.py",
  "cwd": "{frontend_dist_path}",
  "interpreter": "python3",
  "env": {{
    "PORT": "{frontend_port}",
    "PROJECT_NAME": "{project_name}"
  }},
  "error_file": "{project_path}/frontend/logs/error.log",
  "out_file": "{project_path}/frontend/logs/out.log",
  "log_date_format": "YYYY-MM-DD HH:mm:ss Z"
}}
"""

            # Save ecosystem file
            ecosystem_path = frontend_dist_path / f"{app_name}.config.json"
            ecosystem_path.write_text(ecosystem)

            logger.info(f"✓ Frontend PM2 config created: {app_name}")
            return app_name

        except Exception as e:
            logger.error(f"Failed to create frontend service config: {e}")
            raise

    def start_frontend_service(self, app_name: str) -> bool:
        """Start frontend service."""
        try:
            logger.info(f"Starting frontend service: {app_name}")

            result = subprocess.run(
                ["pm2", "start", f"{CLAWD_UI_DIST}/{app_name}.config.json"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"✓ Frontend service started: {app_name}")
                return True
            else:
                logger.error(f"Failed to start frontend service: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to start frontend service: {e}")
            return False


class NginxConfigurator:
    """Manages nginx configuration for projects."""

    def __init__(self):
        self.config_dir = NGINX_CONFIG_DIR
        self.enabled_dir = NGINX_ENABLED_DIR

    def generate_config(self, project_name: str, frontend_port: int, backend_port: int) -> Tuple[str, str]:
        """
        Generate nginx configuration for project.

        Returns:
            Tuple of (frontend_domain, backend_domain)
        """
        try:
            frontend_domain = f"{project_name}.{BASE_DOMAIN}"
            backend_domain = f"{project_name}-api.{BASE_DOMAIN}"

            config = f"""# Frontend: {frontend_domain}
server {{
    listen 80;
    server_name {frontend_domain};

    location / {{
        proxy_pass http://127.0.0.1:{frontend_port};
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

            logger.info(f"✓ Nginx config generated for {project_name}")
            return (frontend_domain, backend_domain, config)

        except Exception as e:
            logger.error(f"Failed to generate nginx config: {e}")
            raise

    def install_config(self, project_name: str, config: str) -> bool:
        """Install nginx configuration and enable it."""
        try:
            config_path = Path(self.config_dir) / f"{project_name}.conf"
            symlink_path = Path(self.enabled_dir) / f"{project_name}.conf"

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
                ["nginx", "-t"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if test_result.returncode != 0:
                logger.error(f"Nginx config test failed: {test_result.stderr}")
                return False

            # Reload nginx
            result = subprocess.run(
                ["nginx", "-s", "reload"],
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
            req = urllib.request.Request(url, timeout=timeout)

            with urllib.request.urlopen(req) as response:
                data = response.read().decode('utf-8')
                result = json.loads(data)

                return result.get('status') == 'ok'

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

        # Overall status
        results["overall"] = all([
            results["frontend_port_open"],
            results["backend_port_open"],
            results["backend_health_ok"]
        ])

        logger.info(f"Overall deployment: {'✓' if results['overall'] else '✗'}")

        return results


class DNSProvisioner:
    """Provisions DNS A records using Hostinger DNS skill."""

    def __init__(self):
        self.skill_dir = HOSTINGER_DNS_SKILL_DIR
        self.skill_path = HOSTINGER_DNS_SKILL
        self.server_ip = SERVER_IP

    def check_subdomain_exists(self, subdomain: str, domain: str = None) -> Tuple[bool, Optional[str]]:
        """
        Check if subdomain already exists.

        Returns:
            Tuple of (exists: bool, current_ip: str or None)
        """
        try:
            if not domain:
                domain = BASE_DOMAIN

            # Call Hostinger DNS skill
            cmd = [
                "/bin/bash", "-c",
                f"source {self.skill_dir}/.env && "
                f"{self.skill_dir}/venv/bin/python {self.skill_path} "
                f"check_subdomain_existence "
                f"'{{\"domain\": \"{domain}\", \"subdomain\": \"{subdomain}\"}}'"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                # Parse output to check if exists and get IP
                if "exists" in output.lower() or "found" in output.lower():
                    # Try to extract IP from output
                    import re
                    ip_match = re.search(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', output)
                    current_ip = ip_match.group(0) if ip_match else None
                    return (True, current_ip)
                return (False, None)
            else:
                logger.error(f"DNS check failed: {result.stderr}")
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
        try:
            if not domain:
                domain = BASE_DOMAIN
            if not ip:
                ip = self.server_ip

            logger.info(f"Creating A record: {subdomain}.{domain} → {ip}")

            # Call Hostinger DNS skill
            cmd = [
                "/bin/bash", "-c",
                f"source {self.skill_dir}/.env && "
                f"{self.skill_dir}/venv/bin/python {self.skill_path} "
                f"create_a_record "
                f"'{{\"domain\": \"{domain}\", \"subdomain\": \"{subdomain}\", \"ip\": \"{ip}\", \"ttl\": {ttl}}}'"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"✓ A record created: {subdomain}.{domain} → {ip}")
                logger.info(f"  Note: DNS propagation takes 5-60 minutes")
                return True
            else:
                logger.error(f"Failed to create A record: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to create A record: {e}")
            return False

    def provision_project_dns(self, project_name: str) -> Dict[str, bool]:
        """
        Provision DNS records for a project (frontend + backend).

        Returns:
            Dict with results for frontend and backend DNS
        """
        results = {
            "frontend": False,
            "backend": False,
            "frontend_exists": False,
            "backend_exists": False
        }

        try:
            frontend_subdomain = project_name
            backend_subdomain = f"{project_name}-api"

            logger.info(f"Provisioning DNS for project: {project_name}")
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

    def __init__(self, project_name: str, project_path: Path):
        self.project_name = project_name
        self.project_path = project_path
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

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"🚀 Starting infrastructure provisioning for {self.project_name}")

            # Phase 1: Allocate ports
            logger.info("Phase 1/6: Port allocation")
            self.ports = {
                "frontend": self.port_allocator.allocate_frontend_port(),
                "backend": self.port_allocator.allocate_backend_port()
            }
            logger.info(f"✓ Ports allocated: {self.ports}")

            # Phase 2: Provision database
            logger.info("Phase 2/6: Database provisioning")
            self.database_info = self.db_provisioner.create_database_and_user(self.project_name)
            logger.info(f"✓ Database created: {self.database_info['database_name']}")

            # Phase 3: Configure backend environment
            logger.info("Phase 3/6: Backend environment configuration")
            self._configure_backend_env()
            logger.info("✓ Backend environment configured")

            # Phase 4: Create service config
            logger.info("Phase 4/6: Service configuration")
            self.service_name = self.service_manager.create_backend_service(
                self.project_name,
                self.ports["backend"],
                self.project_path
            )
            logger.info(f"✓ Service configured: {self.service_name}")

            # Phase 5: Nginx configuration
            logger.info("Phase 5/7: Nginx configuration")
            frontend_domain, backend_domain, config = self.nginx_configurator.generate_config(
                self.project_name,
                self.ports["frontend"],
                self.ports["backend"]
            )
            self.domains = {
                "frontend": frontend_domain,
                "backend": backend_domain
            }
            self.nginx_configurator.install_config(self.project_name, config)
            self.nginx_configurator.reload_nginx()
            logger.info(f"✓ Nginx configured: {self.domains}")

            # Phase 6: DNS provisioning
            logger.info("Phase 6/7: DNS provisioning")
            self.dns_results = self.dns_provisioner.provision_project_dns(self.project_name)
            logger.info(f"✓ DNS provisioned: {self.domains}")

            # Phase 7: Service startup
            logger.info("Phase 7/7: Service startup")

            # Start backend service
            self.service_manager.start_backend_service(self.service_name, self.project_path / "backend")
            logger.info(f"✓ Backend service started: {self.service_name}")

            # Create and start frontend service
            logger.info("Creating frontend service...")
            self.frontend_app_name = self.service_manager.create_frontend_service(
                self.project_name,
                self.ports["frontend"],
                self.project_path
            )

            logger.info(f"✓ Frontend service configured: {self.frontend_app_name}")

            if self.service_manager.start_frontend_service(self.frontend_app_name):
                logger.info(f"✓ Frontend service started: {self.frontend_app_name}")
            else:
                logger.warning(f"⚠️ Frontend service failed to start: {self.frontend_app_name}")

            # Wait for services to start up
            logger.info("Waiting for services to initialize...")
            import time
            time.sleep(3)

            # Verification
            logger.info("Verifying deployment...")
            verification = self.verifier.verify_deployment(
                self.project_name,
                self.ports["frontend"],
                self.ports["backend"]
            )

            if verification["overall"]:
                logger.info("✅ All infrastructure provisioned successfully!")
                self._save_metadata()
                return True
            else:
                logger.error("❌ Deployment verification failed")
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

            if 'BACKEND_PORT' not in [l.split('=')[0] if '=' in l else '' for l in lines]:
                updated_lines.append(f'BACKEND_PORT={self.ports["backend"]}')

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
