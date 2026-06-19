"""
Custom Domain Service

Manages custom customer domains (e.g. www.clientsite.com) for DreamAgent
website projects. One custom domain per project (v1).

This module handles:
- Domain format validation
- DNS verification (CNAME chain resolution, A record resolution,
  Cloudflare/DNS flattening support, server IP comparison)
- CRUD for the `custom_domains` table
- Delegation of nginx config updates and SSL provisioning

Verification accepts any of:
- Direct or multi-hop CNAME chain resolving to the project subdomain
- A record pointing to the server IP (direct or after CNAME flattening)

All DNS values are normalized (lowercase, whitespace stripped, trailing
dots removed) before comparison.

Usage:
    from custom_domain_service import (
        add_domain,
        verify_domain,
        get_project_domain,
        list_all_active,
        remove_domain,
    )
"""

import re
import logging
import subprocess
import ipaddress
from typing import Dict, List, Optional, Any

from database_adapter import get_db

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

BASE_DOMAIN = "dreambigwithai.com"
# Fallback only; real IP is resolved dynamically via _get_server_ip()
SERVER_IP_FALLBACK = "195.200.14.37"

# Valid statuses
STATUS_PENDING = "pending"
STATUS_VERIFIED = "verified"
STATUS_ACTIVE = "active"
STATUS_FAILED = "failed"

# Valid SSL statuses
SSL_PENDING = "pending"
SSL_ACTIVE = "active"
SSL_FAILED = "failed"

# Domain format: allow standard domain names (sub.example.com, example.com, www.example.com)
# Max 253 chars, labels 1-63 chars, alphanumeric + hyphens, not starting/ending with hyphen.
DOMAIN_REGEX = re.compile(
    r"^(?=.{1,253}$)"
    r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)


class DomainValidationError(Exception):
    """Raised when a custom domain fails validation."""
    pass


class DomainConflictError(Exception):
    """Raised when a domain is already assigned to another project."""
    pass


# ============================================================================
# VALIDATION
# ============================================================================

def validate_domain_format(domain: str) -> str:
    """
    Validate a custom domain format. Returns the cleaned (lowercase, stripped)
    domain if valid, raises DomainValidationError otherwise.
    """
    if not domain or not domain.strip():
        raise DomainValidationError("Domain is required")

    domain = domain.strip().lower().rstrip(".")

    if len(domain) > 253:
        raise DomainValidationError("Domain is too long (max 253 characters)")

    if not DOMAIN_REGEX.match(domain):
        raise DomainValidationError(
            "Invalid domain format. Use a valid domain like 'www.example.com' or 'example.com'"
        )

    # Reject the platform's own domain
    if domain == BASE_DOMAIN or domain.endswith("." + BASE_DOMAIN):
        raise DomainValidationError(
            f"Cannot use the platform domain '{BASE_DOMAIN}'. "
            f"Use a subdomain from your own domain."
        )

    return domain


def _is_root_domain(domain: str) -> bool:
    """Check if this is a root domain (no subdomain). e.g. 'example.com' not 'www.example.com'."""
    parts = domain.split(".")
    # TLD is the last part (or last two for co.uk style — simplified for v1)
    return len(parts) <= 2


# ============================================================================
# HELPERS
# ============================================================================

def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Normalize a DB row (dict or tuple) into a plain dict."""
    if isinstance(row, dict):
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "domain": row["domain"],
            "status": row["status"],
            "ssl_status": row["ssl_status"],
            "verified_at": str(row["created_at"]) if row.get("verified_at") else None,
            "created_at": str(row["created_at"]) if row.get("created_at") else None,
            "updated_at": str(row["updated_at"]) if row.get("updated_at") else None,
        }
    return {
        "id": row[0],
        "project_id": row[1],
        "domain": row[2],
        "status": row[3],
        "ssl_status": row[4],
        "verified_at": str(row[5]) if row[5] else None,
        "created_at": str(row[6]) if row[6] else None,
        "updated_at": str(row[7]) if row[7] else None,
    }


# ============================================================================
# DNS INSTRUCTIONS
# ============================================================================

def get_dns_instructions(domain: str, project_subdomain: str) -> Dict[str, Any]:
    """
    Build DNS instructions for the user.

    For non-root domains (www.example.com):
        CNAME www -> project_subdomain.dreambigwithai.com

    For root domains (example.com):
        A @ -> server_ip
        (also recommend CNAME www -> project_subdomain.dreambigwithai.com)
    """
    frontend_target = f"{project_subdomain}.{BASE_DOMAIN}"
    server_ip = _get_server_ip()

    if _is_root_domain(domain):
        return {
            "record_type": "A",
            "type": "A",
            "host": "@",
            "value": server_ip,
            "records": [
                {"type": "A", "host": "@", "value": server_ip, "ttl": "3600"},
                {"type": "CNAME", "host": "www", "value": frontend_target, "ttl": "3600"},
            ],
            "explanation": f"Point your root domain to the server IP ({server_ip}), "
                           f"and optionally add a CNAME for www.",
        }
    else:
        # Subdomain like www.example.com
        # Host is the first label (e.g., "www" for "www.example.com")
        parts = domain.split(".")
        host = parts[0]
        return {
            "record_type": "CNAME",
            "type": "CNAME",
            "host": host,
            "value": frontend_target,
            "records": [
                {"type": "CNAME", "host": host, "value": frontend_target, "ttl": "3600"},
            ],
            "explanation": f"Create a CNAME record pointing {host} to {frontend_target}.",
        }


# ============================================================================
# DNS VERIFICATION
# ============================================================================

# Cache the dynamically-detected server IP so we only query external services
# once per process lifetime.
_server_ip_cache: Optional[str] = None


def _get_server_ip() -> str:
    """
    Detect this server's public IPv4 address at runtime.

    Tries multiple external services (ipify, icanhazip, ifconfig.me) to avoid
    depending on a hardcoded IP that may drift when the server is re-provisioned.

    Returns the detected IP, or falls back to the static default if all lookups
    fail.
    """
    global _server_ip_cache
    if _server_ip_cache:
        return _server_ip_cache

    ipv4_services = [
        "https://api.ipify.org",
        "https://icanhazip.com",
        "https://ifconfig.me/ip",
    ]
    for service in ipv4_services:
        try:
            result = subprocess.run(
                ["curl", "-4", "-s", service],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                ip = result.stdout.strip()
                if "." in ip and ":" not in ip and _is_valid_ip(ip):
                    logger.info(f"[CUSTOM_DOMAIN] Server IPv4 detected: {ip}")
                    _server_ip_cache = ip
                    return ip
        except Exception as e:
            logger.warning(f"[CUSTOM_DOMAIN] Failed to get IP from {service}: {e}")
            continue

    logger.warning(
        f"[CUSTOM_DOMAIN] Could not detect server IP, using fallback {SERVER_IP_FALLBACK}"
    )
    _server_ip_cache = SERVER_IP_FALLBACK
    return _server_ip_cache


def _normalize_dns_value(value: str) -> str:
    """Normalize a DNS value: lowercase, strip whitespace, remove trailing dot."""
    if not value:
        return value
    return value.strip().lower().rstrip(".")


def _is_valid_ip(value: str) -> bool:
    """Check if a string is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value.strip())
        return True
    except (ValueError, ipaddress.AddressValueError):
        return False


def _dig_cname(domain: str) -> Optional[str]:
    """Resolve CNAME for domain using `dig`. Returns normalized target or None."""
    try:
        result = subprocess.run(
            ["dig", "+short", "+time=5", "+tries=1", "CNAME", domain],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip()
        if output:
            # dig may return multiple lines; take the first valid CNAME (non-IP)
            for line in output.split("\n"):
                line = line.strip()
                if line and not _is_valid_ip(line):
                    return _normalize_dns_value(line)
        return None
    except Exception as e:
        logger.warning(f"[CUSTOM_DOMAIN] dig CNAME failed for {domain}: {e}")
        return None


def _dig_a_record(domain: str) -> List[str]:
    """
    Resolve A records for domain using `dig`. Returns list of IPv4/IPv6
    addresses only (filters out CNAME targets that dig may also print).
    """
    try:
        result = subprocess.run(
            ["dig", "+short", "+time=5", "+tries=1", "A", domain],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip()
        ips: List[str] = []
        if output:
            for line in output.split("\n"):
                line = line.strip()
                if line and _is_valid_ip(line):
                    ips.append(line)
        return ips
    except Exception as e:
        logger.warning(f"[CUSTOM_DOMAIN] dig A failed for {domain}: {e}")
        return []


def _dig_cname_chain(domain: str, max_hops: int = 10) -> List[str]:
    """
    Follow the CNAME chain for a domain by iteratively resolving CNAMEs.
    Returns ordered list of CNAME targets (e.g. ['example.com', 'target.example.com']).
    """
    chain: List[str] = []
    current = _normalize_dns_value(domain)
    seen: set = set()

    for _ in range(max_hops):
        current = _normalize_dns_value(current)
        if current in seen:
            break
        seen.add(current)

        cname = _dig_cname(current)
        if not cname:
            break
        chain.append(cname)
        current = cname

    return chain


def verify_dns(domain: str, project_subdomain: str) -> Dict[str, Any]:
    """
    Verify that the domain's DNS points to this project.

    Accepts any of the following:
    - CNAME (direct or multi-hop chain) resolving to the project subdomain
    - A record pointing to the server IP (direct or after CNAME flattening)
    - DNS flattening (e.g. Cloudflare) where CNAME target has the A record

    All values are normalized (lowercase, whitespace stripped, trailing
    dots removed) before comparison.

    Returns dict with:
        verified: bool
        method: "cname" | "a_record" | None
        detail: str
        cname_target: Optional[str]
        cname_chain: List[str]
        a_records: List[str]
        expected_cname: str
        expected_ip: str
    """
    expected_cname = _normalize_dns_value(f"{project_subdomain}.{BASE_DOMAIN}")
    expected_ip = _get_server_ip()

    logger.info(f"[CUSTOM_DOMAIN] === Verifying DNS for {domain} ===")
    logger.info(f"[CUSTOM_DOMAIN] Expected CNAME: {expected_cname}")
    logger.info(f"[CUSTOM_DOMAIN] Expected Server IP: {expected_ip}")

    # --- Step 1: Follow CNAME chain ---
    cname_chain = _dig_cname_chain(domain)
    cname_target = cname_chain[-1] if cname_chain else None

    logger.info(f"[CUSTOM_DOMAIN] Actual CNAME chain: {' -> '.join(cname_chain) if cname_chain else '(none)'}")

    # Check if any link in the CNAME chain matches the expected target.
    # This handles direct CNAME, multi-hop chains, and Cloudflare CNAME flattening.
    if cname_chain:
        for hop in cname_chain:
            hop_norm = _normalize_dns_value(hop)
            if hop_norm == expected_cname:
                logger.info(
                    f"[CUSTOM_DOMAIN] CNAME chain verified: "
                    f"{domain} -> {' -> '.join(cname_chain)}"
                )
                logger.info(f"[CUSTOM_DOMAIN] Verification Result: PASS (cname)")
                return {
                    "verified": True,
                    "method": "cname",
                    "detail": f"CNAME chain resolves to {expected_cname}",
                    "cname_target": cname_target,
                    "cname_chain": cname_chain,
                    "a_records": [],
                    "expected_cname": expected_cname,
                    "expected_ip": expected_ip,
                }

    # --- Step 2: Resolve A records (direct or after CNAME flattening) ---
    a_records = _dig_a_record(domain)

    # If the domain has a CNAME but no direct A record (flattened), resolve
    # A records for the CNAME target instead. This covers Cloudflare/DNS
    # flattening where the authoritative A records live on the target host.
    if not a_records and cname_target:
        a_records = _dig_a_record(cname_target)

    # Also follow the CNAME chain to resolve the final IP at each hop.
    # Some setups resolve to the IP only at the very end of the chain.
    if not a_records and cname_chain:
        for hop in reversed(cname_chain):
            hop_a = _dig_a_record(hop)
            if hop_a:
                a_records = hop_a
                break

    resolved_ips = list(dict.fromkeys(a_records))  # de-duplicate, preserve order
    ip_str = ", ".join(resolved_ips) if resolved_ips else "(none)"
    logger.info(f"[CUSTOM_DOMAIN] Resolved IP: {ip_str}")

    if resolved_ips and expected_ip in resolved_ips:
        logger.info(
            f"[CUSTOM_DOMAIN] A record verified: {domain} -> {ip_str} "
            f"(matches server IP {expected_ip})"
        )
        logger.info(f"[CUSTOM_DOMAIN] Verification Result: PASS (a_record)")
        return {
            "verified": True,
            "method": "a_record",
            "detail": f"Resolves to server IP {expected_ip}",
            "cname_target": cname_target,
            "cname_chain": cname_chain,
            "a_records": resolved_ips,
            "expected_cname": expected_cname,
            "expected_ip": expected_ip,
        }

    # --- Not verified ---
    logger.warning(f"[CUSTOM_DOMAIN] Verification Result: FAIL")
    detail_parts = []
    if cname_chain:
        detail_parts.append(
            f"CNAME chain: {' -> '.join(cname_chain)} "
            f"(expected {expected_cname})"
        )
    else:
        detail_parts.append(f"No CNAME record found (expected {expected_cname})")
    if resolved_ips:
        detail_parts.append(
            f"Resolved IPs: {', '.join(resolved_ips)} "
            f"(expected {expected_ip})"
        )
    else:
        detail_parts.append(f"No A record resolved (expected {expected_ip})")

    return {
        "verified": False,
        "method": None,
        "detail": " | ".join(detail_parts),
        "cname_target": cname_target,
        "cname_chain": cname_chain,
        "a_records": resolved_ips,
        "expected_cname": expected_cname,
        "expected_ip": expected_ip,
    }


# ============================================================================
# SSL / CERTBOT
# ============================================================================

def provision_ssl(domain: str) -> Dict[str, Any]:
    """
    Run certbot to obtain an SSL certificate for the custom domain.

    Uses `certbot --nginx -d <domain>` (non-interactive, expanded).

    Returns:
        Dict with success: bool and message: str.
    """
    try:
        result = subprocess.run(
            [
                "certbot", "certonly", "--nginx",
                "-d", domain,
                "--non-interactive",
                "--agree-tos",
                "--register-unsafely-without-email",
                "--no-eff-email",
            ],
            capture_output=True, text=True, timeout=120,
        )

        if result.returncode == 0:
            logger.info(f"[CUSTOM_DOMAIN] SSL certificate obtained for {domain}")
            return {"success": True, "message": "SSL certificate obtained"}
        else:
            logger.error(f"[CUSTOM_DOMAIN] Certbot failed for {domain}: {result.stderr[:500]}")
            return {"success": False, "message": f"Certbot failed: {result.stderr[:300]}"}
    except FileNotFoundError:
        logger.error("[CUSTOM_DOMAIN] certbot not installed on server")
        return {"success": False, "message": "certbot is not installed on the server"}
    except subprocess.TimeoutExpired:
        logger.error(f"[CUSTOM_DOMAIN] Certbot timed out for {domain}")
        return {"success": False, "message": "Certbot timed out (120s)"}
    except Exception as e:
        logger.error(f"[CUSTOM_DOMAIN] SSL provisioning error for {domain}: {e}")
        return {"success": False, "message": f"SSL error: {str(e)}"}


# ============================================================================
# CRUD
# ============================================================================

def get_project_domain(project_id: int) -> Optional[Dict[str, Any]]:
    """Get the custom domain for a project, or None if none exists."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, project_id, domain, status, ssl_status,
                      verified_at, created_at, updated_at
               FROM custom_domains
               WHERE project_id = ?
               ORDER BY id DESC
               LIMIT 1""",
            (project_id,),
        ).fetchone()

    return _row_to_dict(row) if row else None


def list_all_active() -> List[Dict[str, Any]]:
    """List all verified/active custom domains (for nginx regeneration)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, project_id, domain, status, ssl_status,
                      verified_at, created_at, updated_at
               FROM custom_domains
               WHERE status IN ('verified', 'active')
               ORDER BY domain"""
        ).fetchall()

    return [_row_to_dict(r) for r in rows]


def add_domain(project_id: int, domain: str) -> Dict[str, Any]:
    """
    Add a custom domain to a project.

    Validates format, checks for duplicates, and inserts as 'pending'.

    Raises:
        DomainValidationError: If domain format is invalid.
        DomainConflictError: If domain is already assigned to another project.

    Returns:
        The created domain record dict.
    """
    domain = validate_domain_format(domain)

    # Check if domain is already assigned to ANY project
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id, project_id FROM custom_domains WHERE domain = ?",
            (domain,),
        ).fetchone()

        if existing:
            existing = _row_to_dict(existing) if isinstance(existing, dict) else {
                "id": existing[0], "project_id": existing[1], "domain": domain
            }
            if existing.get("project_id") == project_id:
                raise DomainConflictError(
                    f"Domain '{domain}' is already connected to this project"
                )
            raise DomainConflictError(
                f"Domain '{domain}' is already assigned to another project"
            )

        # Check if this project already has a custom domain (one per project for v1)
        existing_project = conn.execute(
            "SELECT id, domain FROM custom_domains WHERE project_id = ?",
            (project_id,),
        ).fetchone()

        if existing_project:
            raise DomainConflictError(
                "This project already has a custom domain. "
                "Remove it first to add a different one."
            )

        # Insert as pending
        conn.execute(
            """INSERT INTO custom_domains (project_id, domain, status, ssl_status)
               VALUES (?, ?, 'pending', 'pending')""",
            (project_id, domain),
        )
        conn.commit()

    logger.info(f"[CUSTOM_DOMAIN] Added domain '{domain}' to project {project_id} (pending)")
    return get_project_domain(project_id)  # type: ignore[return-value]


def mark_verified(domain_id: int) -> Optional[Dict[str, Any]]:
    """Mark a domain as DNS-verified."""
    with get_db() as conn:
        conn.execute(
            """UPDATE custom_domains
               SET status = 'verified', verified_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (domain_id,),
        )
        conn.commit()

    logger.info(f"[CUSTOM_DOMAIN] Domain {domain_id} marked as verified")
    return get_domain_by_id(domain_id)


def mark_active(domain_id: int) -> Optional[Dict[str, Any]]:
    """Mark a domain as fully active (nginx + SSL done)."""
    with get_db() as conn:
        conn.execute(
            """UPDATE custom_domains
               SET status = 'active', updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (domain_id,),
        )
        conn.commit()

    logger.info(f"[CUSTOM_DOMAIN] Domain {domain_id} marked as active")
    return get_domain_by_id(domain_id)


def mark_ssl_active(domain_id: int) -> Optional[Dict[str, Any]]:
    """Update SSL status to active."""
    with get_db() as conn:
        conn.execute(
            """UPDATE custom_domains
               SET ssl_status = 'active', updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (domain_id,),
        )
        conn.commit()

    logger.info(f"[CUSTOM_DOMAIN] Domain {domain_id} SSL marked active")
    return get_domain_by_id(domain_id)


def mark_failed(domain_id: int, ssl: bool = False) -> Optional[Dict[str, Any]]:
    """Mark a domain (or its SSL) as failed."""
    with get_db() as conn:
        if ssl:
            conn.execute(
                """UPDATE custom_domains
                   SET ssl_status = 'failed', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (domain_id,),
            )
        else:
            conn.execute(
                """UPDATE custom_domains
                   SET status = 'failed', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (domain_id,),
            )
        conn.commit()

    return get_domain_by_id(domain_id)


def get_domain_by_id(domain_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, project_id, domain, status, ssl_status,
                      verified_at, created_at, updated_at
               FROM custom_domains WHERE id = ?""",
            (domain_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def remove_domain(domain_id: int) -> bool:
    """Remove a custom domain record from the database."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT domain FROM custom_domains WHERE id = ?",
            (domain_id,),
        ).fetchone()
        if not row:
            return False

        conn.execute("DELETE FROM custom_domains WHERE id = ?", (domain_id,))
        conn.commit()

    domain_name = row["domain"] if isinstance(row, dict) else row[0]
    logger.info(f"[CUSTOM_DOMAIN] Removed domain '{domain_name}' (id={domain_id})")
    return True


def remove_domain_by_project(project_id: int) -> bool:
    """Remove all custom domains for a project."""
    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM custom_domains WHERE project_id = ?",
            (project_id,),
        )
        conn.commit()
    return True
