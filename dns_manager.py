#!/usr/bin/env python3
"""
Hostinger DNS Manager - Internal DNS management for Clawd Backend

Interact with your Hostinger DNS zones using their official API v1.

Supports:
- List DNS records
- Check subdomain existence
- Create A records
- Delete A records
"""

import os
import json
import logging
from pathlib import Path

try:
    import requests
except ImportError as e:
    print(f"Error: Missing dependency: {e}")
    print("Run: pip install requests")
    exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HostingerDNSAPI:
    """Client for Hostinger DNS API v1."""

    def __init__(self, api_token: str):
        """
        Initialize with API token.

        Get token from: hPanel → Profile → API → Generate new token
        """
        self.api_token = api_token
        self.base_url = "https://developers.hostinger.com/api/dns/v1"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        })

    def list_dns_records(self, domain: str) -> dict:
        """
        List all current DNS records for a domain.

        Returns:
            Dict with records list or error
        """
        try:
            url = f"{self.base_url}/zones/{domain}"
            response = self.session.get(url, timeout=30)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "records": data
                }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "error": "Invalid or expired API token",
                    "status_code": response.status_code
                }
            elif response.status_code == 404:
                return {
                    "success": False,
                    "error": f"Domain '{domain}' not found in your account",
                    "status_code": response.status_code
                }
            else:
                return {
                    "success": False,
                    "error": f"API error: HTTP {response.status_code}",
                    "status_code": response.status_code
                }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Request timeout (30s)"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def check_subdomain_exists(self, domain: str, subdomain: str) -> dict:
        """
        Check if subdomain (A/AAAA/CNAME) already exists and what it points to.

        Returns:
            Dict with exists bool, current IP (if any), and record type
        """
        try:
            url = f"{self.base_url}/zones/{domain}"
            response = self.session.get(url, timeout=30)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to fetch DNS records: HTTP {response.status_code}"
                }

            records = response.json()

            # Check for A, AAAA, and CNAME records
            for record in records:
                if record.get("name", "").lower() == subdomain.lower():
                    # Check if there are records and get first one's content
                    if record.get("records") and len(record["records"]) > 0:
                        current_ip = record["records"][0].get("content")
                        return {
                            "success": True,
                            "exists": True,
                            "name": record.get("name"),
                            "type": record.get("type"),
                            "value": current_ip,
                            "ttl": record.get("ttl")
                        }

            return {
                "success": True,
                "exists": False,
                "message": f"Subdomain '{subdomain}' does not exist"
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def delete_a_record(self, domain: str, subdomain: str) -> dict:
        """
        Delete a subdomain's DNS records.

        Args:
            domain: Base domain (e.g., "dreambigwithai.com")
            subdomain: Subdomain name to delete (e.g., "cryptoprice")

        Returns:
            Dict with success status and message
        """
        try:
            url = f"{self.base_url}/zones/{domain}"
            full_domain = f"{subdomain}.{domain}"

            # First, get all current records
            get_response = self.session.get(url, timeout=30)
            if get_response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to fetch current DNS records: HTTP {get_response.status_code}"
                }

            current_records = get_response.json()

            # Filter out the subdomain record we want to delete
            # Keep all records except those matching subdomain name
            updated_records = [r for r in current_records if r.get("name", "").lower() != subdomain.lower()]

            # PUT the updated records back (wrapped in zone array with overwrite)
            record_data = {
                "overwrite": True,
                "zone": updated_records
            }

            put_response = self.session.put(url, json=record_data, timeout=30)

            if put_response.status_code == 200:
                return {
                    "success": True,
                    "message": f"DNS record deleted: {full_domain}",
                    "records_count": len(updated_records)
                }
            elif put_response.status_code == 400:
                error_msg = put_response.json().get("error", "Invalid parameters")
                return {
                    "success": False,
                    "error": f"Bad request: {error_msg}",
                    "status_code": 400
                }
            elif put_response.status_code == 401:
                return {
                    "success": False,
                    "error": "Invalid or expired API token",
                    "status_code": 401
                }
            elif put_response.status_code == 404:
                return {
                    "success": False,
                    "error": f"Domain '{domain}' not found in your account",
                    "status_code": 404
                }
            elif put_response.status_code == 422:
                error_msg = put_response.json().get("error", "Validation failed")
                return {
                    "success": False,
                    "error": f"Validation error: {error_msg}",
                    "status_code": 422
                }
            elif put_response.status_code == 423:
                return {
                    "success": False,
                    "error": f"Rate limit exceeded. Wait 15-60 minutes.",
                    "status_code": 423
                }
            else:
                return {
                    "success": False,
                    "error": f"API error: HTTP {put_response.status_code}",
                    "status_code": put_response.status_code
                }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Request timeout (30s)"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def create_a_record(self, domain: str, subdomain: str, ip: str, ttl: int = 14400) -> dict:
        """
        Create a new A record (subdomain → IPv4 address).

        Args:
            domain: Base domain (e.g., "dreambigwithai.com")
            subdomain: Subdomain name (e.g., "cryptoprice")
            ip: Target IPv4 address (e.g., "195.200.14.37")
            ttl: Time to live in seconds (default: 14400)

        Returns:
            Dict with success status and message
        """
        try:
            url = f"{self.base_url}/zones/{domain}"
            full_domain = f"{subdomain}.{domain}"

            # Correct payload structure per Hostinger API documentation
            record_data = {
                "overwrite": True,
                "zone": [{
                    "name": subdomain,
                    "records": [{
                        "content": ip
                    }],
                    "ttl": ttl,
                    "type": "A"
                }]
            }

            response = self.session.put(url, json=record_data, timeout=30)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": f"A record created: {full_domain} → {ip}",
                    "record": response.json()
                }
            elif response.status_code == 400:
                error_msg = response.json().get("error", "Invalid parameters")
                return {
                    "success": False,
                    "error": f"Bad request: {error_msg}",
                    "status_code": 400
                }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "error": "Invalid or expired API token",
                    "status_code": 401
                }
            elif response.status_code == 404:
                return {
                    "success": False,
                    "error": f"Domain '{domain}' not found in your account",
                    "status_code": 404
                }
            elif response.status_code == 422:
                error_msg = response.json().get("error", "Validation failed")
                return {
                    "success": False,
                    "error": f"Validation error: {error_msg}",
                    "status_code": 422
                }
            elif response.status_code == 423:
                return {
                    "success": False,
                    "error": f"Rate limit exceeded. Wait 15-60 minutes.",
                    "status_code": 423
                }
            else:
                return {
                    "success": False,
                    "error": f"API error: HTTP {response.status_code}",
                    "status_code": response.status_code
                }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Request timeout (30s)"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


def get_api_token() -> str:
    """Get Hostinger API token from environment variable."""
    api_token = os.getenv("HOSTINGER_API_TOKEN")
    if not api_token or api_token == "your_token_here":
        raise ValueError("HOSTINGER_API_TOKEN not set. Set in .env file.")
    return api_token


def list_dns_records(domain: str) -> dict:
    """
    List all current DNS records for a domain.

    Args:
        domain: Domain name (e.g., "dreambigwithai.com")

    Returns:
        Dict with records list or error
    """
    api_token = get_api_token()
    client = HostingerDNSAPI(api_token)
    return client.list_dns_records(domain)


def check_subdomain_exists(domain: str, subdomain: str) -> dict:
    """
    Check if subdomain (A/AAAA/CNAME) already exists and what it points to.

    Args:
        domain: Base domain (e.g., "dreambigwithai.com")
        subdomain: Subdomain name (e.g., "cryptoprice")

    Returns:
        Dict with exists bool, current IP, record type, and details
    """
    api_token = get_api_token()
    client = HostingerDNSAPI(api_token)
    return client.check_subdomain_exists(domain, subdomain)


def create_a_record(domain: str, subdomain: str, ip: str, ttl: int = 14400) -> dict:
    """
    Create a new A record (subdomain → IPv4 address).

    Args:
        domain: Base domain (e.g., "dreambigwithai.com")
        subdomain: Subdomain name (e.g., "cryptoprice")
        ip: Target IPv4 address (e.g., "195.200.14.37")
        ttl: Time to live in seconds (default: 14400)

    Returns:
        Dict with success status and message
    """
    api_token = get_api_token()
    client = HostingerDNSAPI(api_token)
    return client.create_a_record(domain, subdomain, ip, ttl)


def delete_a_record(domain: str, subdomain: str) -> dict:
    """
    Delete a subdomain's DNS records.

    Args:
        domain: Base domain (e.g., "dreambigwithai.com")
        subdomain: Subdomain name to delete (e.g., "cryptoprice")

    Returns:
        Dict with success status and message
    """
    api_token = get_api_token()
    client = HostingerDNSAPI(api_token)
    return client.delete_a_record(domain, subdomain)
