"""
DNS Provisioning Manager

Handles DNS record creation and deletion for DreamPilot projects using local DNS manager.
"""

import os
import logging
from typing import Dict, Tuple, Optional
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Infrastructure settings
BASE_DOMAIN = "dreambigwithai.com"
SERVER_IP = "195.200.14.37"  # Default server IP for DNS A records


class DNSProvisioner:
    """Provisions DNS A records using local DNS manager."""

    def __init__(self):
        """Initialize DNS provisioner."""
        # Import dns_manager (must be in same directory)
        try:
            import dns_manager
            self.dns_manager = dns_manager
            self.dns_available = True
        except ImportError as e:
            logger.warning(f"⚠️ DNS manager not available: {e}")
            logger.warning(f"  DNS provisioning will be skipped")
            self.dns_available = False

    def check_subdomain_exists(self, subdomain: str, domain: str = None) -> Tuple[bool, Optional[str]]:
        """
        Check if subdomain already exists.

        Returns:
            Tuple of (exists: bool, current_ip: str or None)
        """
        if not self.dns_available:
            return (False, None)

        try:
            if not domain:
                domain = BASE_DOMAIN

            # Call dns_manager to check subdomain
            result = self.dns_manager.check_subdomain_exists(domain, subdomain)

            if result.get("success") and result.get("exists"):
                current_ip = result.get("value")
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
        if not self.dns_available:
            logger.warning(f"  Skipping DNS A record creation (DNS manager not available)")
            logger.warning(f"  Manually create A record: {subdomain}.{BASE_DOMAIN} → {self.server_ip}")
            return False

        try:
            if not domain:
                domain = BASE_DOMAIN
            if not ip:
                ip = SERVER_IP

            logger.info(f"Creating A record: {subdomain}.{domain} → {ip}")

            # Call dns_manager to create record
            result = self.dns_manager.create_a_record(domain, subdomain, ip, ttl)

            if result.get("success"):
                logger.info(f"✓ A record created: {subdomain}.{domain} → {ip}")
                logger.info(f"  Note: DNS propagation takes 5-60 minutes")
                return True
            else:
                logger.error(f"Failed to create A record:")
                logger.error(f"  Error: {result.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Failed to create A record: {e}")
            return False

    def delete_a_record(self, subdomain: str, domain: str = None) -> bool:
        """
        Delete A record for subdomain.

        Returns:
            True if successful, False otherwise
        """
        if not self.dns_available:
            logger.warning(f"  Skipping DNS A record deletion (DNS manager not available)")
            logger.warning(f"  Manually delete A record: {subdomain}.{BASE_DOMAIN}")
            return False

        try:
            if not domain:
                domain = BASE_DOMAIN

            logger.info(f"Deleting A record: {subdomain}.{domain}")

            # Call dns_manager to delete record
            result = self.dns_manager.delete_a_record(domain, subdomain)

            if result.get("success"):
                logger.info(f"✓ A record deleted: {subdomain}.{domain}")
                logger.info(f"  Note: DNS propagation takes 5-60 minutes")
                return True
            else:
                logger.error(f"Failed to delete A record:")
                logger.error(f"  Error: {result.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Failed to delete A record: {e}")
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

        # Skip DNS provisioning if dns_manager is not available
        if not self.dns_available:
            logger.warning(f"⚠️ DNS provisioning skipped (DNS manager not available)")
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
                    if frontend_current_ip == SERVER_IP:
                        logger.info(f"    ✓ Already pointing to correct server IP")
                        results["frontend"] = True
                    else:
                        logger.warning(f"    ⚠️ Pointing to different IP: {frontend_current_ip} (ours: {SERVER_IP})")
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
                    if backend_current_ip == SERVER_IP:
                        logger.info(f"    ✓ Already pointing to correct server IP")
                        results["backend"] = True
                    else:
                        logger.warning(f"    ⚠️ Pointing to different IP: {backend_current_ip} (ours: {SERVER_IP})")
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

    def cleanup_project_dns(self, domain: str, project_name: str = "project") -> Dict[str, bool]:
        """
        Cleanup DNS records for a project (frontend + backend).

        Args:
            domain: Domain name (e.g., "ecommerce22")
            project_name: Project name (for logging, optional)

        Returns:
            Dict with cleanup results
        """
        results = {
            "frontend_deleted": False,
            "backend_deleted": False,
            "skipped": False,
            "errors": []
        }

        # Skip DNS cleanup if dns_manager is not available
        if not self.dns_available:
            logger.warning(f"⚠️ DNS cleanup skipped (DNS manager not available)")
            logger.warning(f"  Remove these A records manually in Hostinger hPanel:")
            logger.warning(f"    - {domain}.{BASE_DOMAIN}")
            logger.warning(f"    - {domain}-api.{BASE_DOMAIN}")
            results["skipped"] = True
            return results

        try:
            frontend_subdomain = domain
            backend_subdomain = f"{domain}-api"

            logger.info(f"Cleaning up DNS for project: {project_name} (domain: {domain})")

            # Delete frontend DNS record
            if self.delete_a_record(frontend_subdomain):
                results["frontend_deleted"] = True
            else:
                results["errors"].append(f"Failed to delete frontend DNS record")

            # Delete backend DNS record
            if self.delete_a_record(backend_subdomain):
                results["backend_deleted"] = True
            else:
                results["errors"].append(f"Failed to delete backend DNS record")

            # Summary
            logger.info(f"✓ DNS cleanup complete:")
            logger.info(f"    Frontend: {'✓' if results['frontend_deleted'] else '✗'} {frontend_subdomain}.{BASE_DOMAIN}")
            logger.info(f"    Backend:  {'✓' if results['backend_deleted'] else '✗'} {backend_subdomain}.{BASE_DOMAIN}")

            return results

        except Exception as e:
            logger.error(f"Failed to cleanup project DNS: {e}")
            results["errors"].append(str(e))
            return results


# Convenience functions for backward compatibility
def check_subdomain_exists(subdomain: str, domain: str = None) -> Tuple[bool, Optional[str]]:
    """
    Check if subdomain already exists (convenience function).

    Returns:
        Tuple of (exists: bool, current_ip: str or None)
    """
    provisioner = DNSProvisioner()
    return provisioner.check_subdomain_exists(subdomain, domain)


def create_a_record(subdomain: str, domain: str = None, ip: str = None, ttl: int = 14400) -> bool:
    """
    Create A record for subdomain (convenience function).

    Returns:
        True if successful, False otherwise
    """
    provisioner = DNSProvisioner()
    return provisioner.create_a_record(subdomain, domain, ip, ttl)


def delete_a_record(subdomain: str, domain: str = None) -> bool:
    """
    Delete A record for subdomain (convenience function).

    Returns:
        True if successful, False otherwise
    """
    provisioner = DNSProvisioner()
    return provisioner.delete_a_record(subdomain, domain)


def provision_project_dns(domain: str, project_name: str = "project") -> Dict[str, bool]:
    """
    Provision DNS records for a project (convenience function).

    Args:
        domain: Domain name (e.g., "ecommerce22")
        project_name: Project name (for logging, optional)

    Returns:
        Dict with results for frontend and backend DNS
    """
    provisioner = DNSProvisioner()
    return provisioner.provision_project_dns(domain, project_name)


def cleanup_project_dns(domain: str, project_name: str = "project") -> Dict[str, bool]:
    """
    Cleanup DNS records for a project (convenience function).

    Args:
        domain: Domain name (e.g., "ecommerce22")
        project_name: Project name (for logging, optional)

    Returns:
        Dict with cleanup results
    """
    provisioner = DNSProvisioner()
    return provisioner.cleanup_project_dns(domain, project_name)
