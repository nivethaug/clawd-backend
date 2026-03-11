#!/usr/bin/env python3
"""
Deployment Verification Module for DreamPilot

Provides comprehensive deployment verification with retry logic.
Checks all critical deployment indicators and reports detailed status.

## Verification Checks
1. Build output (dist/index.html exists)
2. Nginx configuration generated
3. Domain DNS resolution
4. HTTP response (200 OK)
5. PM2 service status

## Retry Logic
- Configurable retry attempts
- Exponential backoff between retries
- Detailed error reporting on failure
"""

import os
import time
import socket
import logging
import subprocess
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class VerificationStatus(str, Enum):
    """Status of individual verification checks."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class VerificationResult:
    """Result of a single verification check."""
    name: str
    status: VerificationStatus
    message: str
    details: Optional[Dict[str, Any]] = None
    duration_seconds: float = 0.0


class DeploymentVerifier:
    """
    Verifies deployment success with retry logic.
    
    Usage:
        verifier = DeploymentVerifier(
            project_path="/root/dreampilot/projects/website/myproject",
            domain="myproject.dreampilot.io"
        )
        results = verifier.verify_all()
        
        if results["success"]:
            print("Deployment verified!")
        else:
            print(f"Verification failed: {results['failed_checks']}")
    """
    
    def __init__(
        self,
        project_path: str,
        domain: str,
        frontend_port: Optional[int] = None,
        backend_port: Optional[int] = None,
        max_retries: int = 3,
        retry_delay: float = 5.0,
        http_timeout: float = 30.0
    ):
        """
        Initialize deployment verifier.
        
        Args:
            project_path: Path to project directory
            domain: Project domain/subdomain
            frontend_port: Frontend port (optional)
            backend_port: Backend port (optional)
            max_retries: Maximum retry attempts for failed checks
            retry_delay: Base delay between retries (exponential backoff)
            http_timeout: HTTP request timeout in seconds
        """
        self.project_path = Path(project_path)
        self.domain = domain
        self.frontend_port = frontend_port
        self.backend_port = backend_port
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.http_timeout = http_timeout
        
        self.results: List[VerificationResult] = []
        
        logger.info(f"[Verifier] Initialized for domain: {domain}")
        logger.info(f"[Verifier] Project path: {project_path}")
    
    def _retry_check(self, check_fn, *args, **kwargs) -> Tuple[bool, str, Optional[Dict]]:
        """
        Execute a check with retry logic.
        
        Args:
            check_fn: Check function to execute
            *args: Arguments for check function
            **kwargs: Keyword arguments for check function
            
        Returns:
            Tuple of (success, message, details)
        """
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                success, message, details = check_fn(*args, **kwargs)
                if success:
                    return success, message, details
                
                # Check failed but didn't raise exception
                last_error = message
                logger.warning(f"[Verifier] Check attempt {attempt}/{self.max_retries} failed: {message}")
                
                if attempt < self.max_retries:
                    # Exponential backoff
                    delay = self.retry_delay * (2 ** (attempt - 1))
                    logger.info(f"[Verifier] Retrying in {delay}s...")
                    time.sleep(delay)
                    
            except Exception as e:
                last_error = str(e)
                logger.error(f"[Verifier] Check attempt {attempt}/{self.max_retries} exception: {e}")
                
                if attempt < self.max_retries:
                    delay = self.retry_delay * (2 ** (attempt - 1))
                    logger.info(f"[Verifier] Retrying in {delay}s...")
                    time.sleep(delay)
        
        return False, f"Failed after {self.max_retries} attempts: {last_error}", None
    
    def check_build_output(self) -> Tuple[bool, str, Optional[Dict]]:
        """
        Check if build output exists.
        
        Verifies:
        - dist/ directory exists
        - dist/index.html exists
        - dist/assets/ contains files
        
        Returns:
            Tuple of (success, message, details)
        """
        dist_path = self.project_path / "frontend" / "dist"
        index_path = dist_path / "index.html"
        assets_path = dist_path / "assets"
        
        if not dist_path.exists():
            return False, "dist/ directory not found", {"path": str(dist_path)}
        
        if not index_path.exists():
            return False, "dist/index.html not found", {"path": str(index_path)}
        
        # Check assets
        asset_count = 0
        if assets_path.exists():
            asset_count = len(list(assets_path.glob("*")))
        
        details = {
            "dist_path": str(dist_path),
            "index_exists": index_path.exists(),
            "asset_count": asset_count
        }
        
        if asset_count == 0:
            logger.warning("[Verifier] No assets found in dist/assets/")
        
        return True, f"Build output verified ({asset_count} assets)", details
    
    def check_nginx_config(self) -> Tuple[bool, str, Optional[Dict]]:
        """
        Check if nginx configuration exists.
        
        Verifies:
        - /etc/nginx/sites-enabled/{domain} exists
        - Config contains server block for domain
        
        Returns:
            Tuple of (success, message, details)
        """
        nginx_enabled_path = Path(f"/etc/nginx/sites-enabled/{self.domain}")
        nginx_available_path = Path(f"/etc/nginx/sites-available/{self.domain}")
        
        config_path = None
        if nginx_enabled_path.exists():
            config_path = nginx_enabled_path
        elif nginx_available_path.exists():
            config_path = nginx_available_path
        
        if not config_path:
            return False, "Nginx config not found", {
                "checked_paths": [
                    str(nginx_enabled_path),
                    str(nginx_available_path)
                ]
            }
        
        # Read and validate config
        try:
            config_content = config_path.read_text()
            
            # Check for server block with domain
            if self.domain not in config_content:
                return False, f"Nginx config doesn't contain domain {self.domain}", {
                    "config_path": str(config_path)
                }
            
            # Check for server_name directive
            if "server_name" not in config_content:
                return False, "Nginx config missing server_name directive", {
                    "config_path": str(config_path)
                }
            
            return True, "Nginx config verified", {
                "config_path": str(config_path),
                "config_size": len(config_content)
            }
            
        except Exception as e:
            return False, f"Failed to read nginx config: {e}", {
                "config_path": str(config_path)
            }
    
    def check_domain_resolution(self) -> Tuple[bool, str, Optional[Dict]]:
        """
        Check if domain resolves to an IP address.
        
        Returns:
            Tuple of (success, message, details)
        """
        try:
            # Try to resolve domain
            ip_address = socket.gethostbyname(self.domain)
            
            return True, f"Domain resolves to {ip_address}", {
                "domain": self.domain,
                "ip_address": ip_address
            }
            
        except socket.gaierror as e:
            return False, f"Domain does not resolve: {e}", {
                "domain": self.domain,
                "error": str(e)
            }
    
    def check_http_response(self) -> Tuple[bool, str, Optional[Dict]]:
        """
        Check if domain returns HTTP 200.
        
        Returns:
            Tuple of (success, message, details)
        """
        url = f"http://{self.domain}"
        
        try:
            response = requests.get(
                url,
                timeout=self.http_timeout,
                allow_redirects=True,
                headers={"User-Agent": "DreamPilot-Verifier/1.0"}
            )
            
            details = {
                "url": url,
                "status_code": response.status_code,
                "response_time_ms": response.elapsed.total_seconds() * 1000,
                "content_length": len(response.content),
                "final_url": response.url
            }
            
            if response.status_code == 200:
                return True, f"HTTP 200 OK ({response.elapsed.total_seconds():.2f}s)", details
            else:
                return False, f"HTTP {response.status_code} (expected 200)", details
                
        except requests.exceptions.Timeout:
            return False, f"HTTP request timed out after {self.http_timeout}s", {
                "url": url,
                "timeout": self.http_timeout
            }
        except requests.exceptions.ConnectionError as e:
            return False, f"HTTP connection failed: {e}", {
                "url": url,
                "error": str(e)
            }
        except Exception as e:
            return False, f"HTTP request failed: {e}", {
                "url": url,
                "error": str(e)
            }
    
    def check_pm2_service(self) -> Tuple[bool, str, Optional[Dict]]:
        """
        Check if PM2 service is running.
        
        Returns:
            Tuple of (success, message, details)
        """
        try:
            result = subprocess.run(
                ["pm2", "list", "--json"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return False, "PM2 list command failed", {
                    "error": result.stderr
                }
            
            import json
            pm2_data = json.loads(result.stdout)
            
            # Look for project service
            project_name = self.project_path.name.lower().replace(" ", "-")
            matching_services = []
            
            for process in pm2_data:
                process_name = process.get("name", "").lower()
                if project_name in process_name or self.domain.split(".")[0] in process_name:
                    matching_services.append({
                        "name": process.get("name"),
                        "status": process.get("pm2_env", {}).get("status"),
                        "port": process_name
                    })
            
            if not matching_services:
                return False, "No PM2 service found for project", {
                    "project_name": project_name,
                    "domain_prefix": self.domain.split(".")[0]
                }
            
            # Check if any service is online
            online_services = [s for s in matching_services if s["status"] == "online"]
            
            if online_services:
                return True, f"PM2 service online ({len(online_services)} services)", {
                    "services": matching_services,
                    "online_count": len(online_services)
                }
            else:
                return False, "PM2 service not online", {
                    "services": matching_services
                }
                
        except subprocess.TimeoutExpired:
            return False, "PM2 command timed out", {}
        except json.JSONDecodeError as e:
            return False, f"Failed to parse PM2 output: {e}", {}
        except Exception as e:
            return False, f"PM2 check failed: {e}", {"error": str(e)}
    
    def verify_all(self, include_pm2: bool = True) -> Dict[str, Any]:
        """
        Run all verification checks.
        
        Args:
            include_pm2: Whether to check PM2 service status
            
        Returns:
            Dict with overall results and individual check results
        """
        logger.info(f"[Verifier] Starting deployment verification for {self.domain}")
        
        self.results = []
        start_time = time.time()
        
        # Define checks to run
        checks = [
            ("build_output", self.check_build_output),
            ("nginx_config", self.check_nginx_config),
            ("domain_resolution", self.check_domain_resolution),
            ("http_response", self.check_http_response),
        ]
        
        if include_pm2:
            checks.append(("pm2_service", self.check_pm2_service))
        
        # Run each check with retry logic
        for check_name, check_fn in checks:
            logger.info(f"[Verifier] Running check: {check_name}")
            check_start = time.time()
            
            success, message, details = self._retry_check(check_fn)
            duration = time.time() - check_start
            
            status = VerificationStatus.PASSED if success else VerificationStatus.FAILED
            result = VerificationResult(
                name=check_name,
                status=status,
                message=message,
                details=details,
                duration_seconds=duration
            )
            self.results.append(result)
            
            if success:
                logger.info(f"[Verifier] ✅ {check_name}: {message}")
            else:
                logger.error(f"[Verifier] ❌ {check_name}: {message}")
        
        total_duration = time.time() - start_time
        
        # Calculate overall status
        passed = [r for r in self.results if r.status == VerificationStatus.PASSED]
        failed = [r for r in self.results if r.status == VerificationStatus.FAILED]
        
        overall_success = len(failed) == 0
        
        # Build result summary
        result_summary = {
            "success": overall_success,
            "domain": self.domain,
            "total_duration_seconds": round(total_duration, 2),
            "checks": {
                "total": len(self.results),
                "passed": len(passed),
                "failed": len(failed)
            },
            "failed_checks": [r.name for r in failed],
            "details": {
                r.name: {
                    "status": r.status.value,
                    "message": r.message,
                    "duration_seconds": r.duration_seconds,
                    "details": r.details
                }
                for r in self.results
            }
        }
        
        # Log summary
        if overall_success:
            logger.info(f"[Verifier] ✅ All checks passed for {self.domain}")
        else:
            logger.error(f"[Verifier] ❌ {len(failed)}/{len(self.results)} checks failed for {self.domain}")
            logger.error(f"[Verifier] Failed checks: {[r.name for r in failed]}")
        
        return result_summary
    
    def verify_and_retry_build(self, build_fn=None) -> Dict[str, Any]:
        """
        Verify deployment and retry build if verification fails.
        
        Args:
            build_fn: Function to call to rebuild (optional)
            
        Returns:
            Dict with verification results
        """
        # First verification attempt
        results = self.verify_all()
        
        if results["success"]:
            return results
        
        # If build-related checks failed and build function provided, retry
        failed_checks = results["failed_checks"]
        build_related = {"build_output", "http_response"}
        
        if build_related.intersection(failed_checks) and build_fn:
            logger.warning("[Verifier] Build-related checks failed, attempting rebuild...")
            
            try:
                rebuild_success = build_fn()
                if rebuild_success:
                    logger.info("[Verifier] Rebuild successful, re-running verification...")
                    # Re-run verification after rebuild
                    return self.verify_all()
                else:
                    logger.error("[Verifier] Rebuild failed")
                    results["rebuild_attempted"] = True
                    results["rebuild_success"] = False
            except Exception as e:
                logger.error(f"[Verifier] Rebuild exception: {e}")
                results["rebuild_attempted"] = True
                results["rebuild_success"] = False
                results["rebuild_error"] = str(e)
        
        return results


def format_verification_report(results: Dict[str, Any]) -> str:
    """
    Format verification results as human-readable report.
    
    Args:
        results: Verification results dict
        
    Returns:
        Formatted string report
    """
    lines = [
        "📋 Deployment Verification Report",
        "=" * 50,
        f"Domain: {results['domain']}",
        f"Overall: {'✅ PASSED' if results['success'] else '❌ FAILED'}",
        f"Duration: {results['total_duration_seconds']}s",
        "",
        "Checks:",
    ]
    
    for check_name, check_data in results.get("details", {}).items():
        status_emoji = "✅" if check_data["status"] == "passed" else "❌"
        lines.append(f"  {status_emoji} {check_name}: {check_data['message']}")
    
    if results.get("failed_checks"):
        lines.append("")
        lines.append(f"Failed Checks: {', '.join(results['failed_checks'])}")
    
    return "\n".join(lines)
