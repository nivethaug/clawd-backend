"""
Central domain configuration for the DreamAgent platform.

All domain-related constants live here so the base domain can be changed
in a single place. Import from this module instead of hardcoding.
"""

import os

# ---------------------------------------------------------------------------
# Base domain
# ---------------------------------------------------------------------------

# The root domain for all auto-generated project subdomains.
# Set DREAM_DOMAIN env-var to override at runtime (useful for staged rollouts).
BASE_DOMAIN = os.getenv("DREAM_DOMAIN", "dreamagent.cloud")

# ---------------------------------------------------------------------------
# Server / infrastructure
# ---------------------------------------------------------------------------

# Public IP of the origin server (used for DNS A records).
SERVER_IP = os.getenv("SERVER_IP", "195.200.14.37")

# Wildcard SSL certificate paths (LetsEncrypt / certbot layout).
WILDCARD_SSL_CERT = f"/etc/letsencrypt/live/{BASE_DOMAIN}/fullchain.pem"
WILDCARD_SSL_KEY = f"/etc/letsencrypt/live/{BASE_DOMAIN}/privkey.pem"

# ---------------------------------------------------------------------------
# Control-plane hosts (builder / API servers — NOT project subdomains)
# ---------------------------------------------------------------------------

CONTROL_API_HOST = os.getenv("CONTROL_API_HOST", f"api.{BASE_DOMAIN}")
CONTROL_BUILDER_HOST = os.getenv("CONTROL_BUILDER_HOST", f"builderapi.{BASE_DOMAIN}")

# ---------------------------------------------------------------------------
# Email defaults
# ---------------------------------------------------------------------------

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", f"dreamagent@{BASE_DOMAIN}")
DEFAULT_SUPPORT_EMAIL = os.getenv("DEFAULT_SUPPORT_EMAIL", f"support@{BASE_DOMAIN}")
DEFAULT_BOT_EMAIL = os.getenv("DEFAULT_BOT_EMAIL", f"bot@{BASE_DOMAIN}")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def frontend_domain(subdomain: str) -> str:
    """Return the full frontend domain for a project subdomain."""
    return f"{subdomain}.{BASE_DOMAIN}"


def backend_domain(subdomain: str) -> str:
    """Return the full backend domain for a project subdomain."""
    return f"{subdomain}-api.{BASE_DOMAIN}"


def frontend_url(subdomain: str) -> str:
    """Return the full https frontend URL for a project subdomain."""
    return f"https://{frontend_domain(subdomain)}"


def backend_url(subdomain: str) -> str:
    """Return the full https backend URL for a project subdomain."""
    return f"https://{backend_domain(subdomain)}"


def webhook_url(subdomain: str, path: str = "/webhook") -> str:
    """Return the full webhook URL for a project subdomain."""
    return f"{backend_url(subdomain)}{path}"
