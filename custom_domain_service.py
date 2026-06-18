"""
Custom Domain Service

Manages custom customer domains (e.g. www.clientsite.com) for DreamAgent
website projects. One custom domain per project (v1).

This module handles:
- Domain format validation
- DNS verification (CNAME / A record lookup via `dig`)
- CRUD for the `custom_domains` table
- Delegation of nginx config updates and SSL provisioning

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
from typing import Dict, List, Optional, Any

from database_adapter import get_db

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

BASE_DOMAIN = "dreambigwithai.com"
SERVER_IP = "195.200.14.37"

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
        A @ -> SERVER_IP
        (also recommend CNAME www -> project_subdomain.dreambigwithai.com)
    """
    frontend_target = f"{project_subdomain}.{BASE_DOMAIN}"

    if _is_root_domain(domain):
        return {
            "type": "A",
            "host": "@",
            "value": SERVER_IP,
            "records": [
                {"type": "A", "host": "@", "value": SERVER_IP},
                {"type": "CNAME", "host": "www", "value": frontend_target},
            ],
            "explanation": f"Point your root domain to the server IP ({SERVER_IP}), "
                           f"and optionally add a CNAME for www.",
        }
    else:
        # Subdomain like www.example.com
        # Host is the first label (e.g., "www" for "www.example.com")
        parts = domain.split(".")
        host = parts[0]
        return {
            "type": "CNAME",
            "host": host,
            "value": frontend_target,
            "records": [
                {"type": "CNAME", "host": host, "value": frontend_target},
            ],
            "explanation": f"Create a CNAME record pointing {host} to {frontend_target}.",
        }


# ============================================================================
# DNS VERIFICATION
# ============================================================================

def _dig_cname(domain: str) -> Optional[str]:
    """Resolve CNAME for domain using `dig`. Returns target or None."""
    try:
        result = subprocess.run(
            ["dig", "+short", "+time=5", "+tries=1", "CNAME", domain],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip().rstrip(".")
        if output:
            # dig may return multiple lines; take the first valid CNAME
            for line in output.split("\n"):
                line = line.strip().rstrip(".")
                if line:
                    return line
        return None
    except Exception as e:
        logger.warning(f"[CUSTOM_DOMAIN] dig CNAME failed for {domain}: {e}")
        return None


def _dig_a_record(domain: str) -> List[str]:
    """Resolve A records for domain using `dig`. Returns list of IPs or empty list."""
    try:
        result = subprocess.run(
            ["dig", "+short", "+time=5", "+tries=1", "A", domain],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip()
        if output:
            return [ip.strip() for ip in output.split("\n") if ip.strip()]
        return []
    except Exception as e:
        logger.warning(f"[CUSTOM_DOMAIN] dig A failed for {domain}: {e}")
        return []


def verify_dns(domain: str, project_subdomain: str) -> Dict[str, Any]:
    """
    Verify that the domain's DNS points to this project.

    Checks:
    - CNAME: domain -> project_subdomain.dreambigwithai.com
    - A record: domain -> SERVER_IP

    Returns dict with:
        verified: bool
        method: "cname" | "a_record" | None
        detail: str
        cname_target: Optional[str]
        a_records: List[str]
    """
    expected_cname = f"{project_subdomain}.{BASE_DOMAIN}"

    # --- Try CNAME first ---
    cname_target = _dig_cname(domain)
    if cname_target:
        cname_target_clean = cname_target.rstrip(".")
        if cname_target_clean == expected_cname or cname_target_clean == expected_cname.rstrip("."):
            logger.info(f"[CUSTOM_DOMAIN] CNAME verified: {domain} -> {cname_target_clean}")
            return {
                "verified": True,
                "method": "cname",
                "detail": f"CNAME points to {expected_cname}",
                "cname_target": cname_target_clean,
                "a_records": [],
            }

    # --- Try A record ---
    a_records = _dig_a_record(domain)
    if a_records and SERVER_IP in a_records:
        logger.info(f"[CUSTOM_DOMAIN] A record verified: {domain} -> {SERVER_IP}")
        return {
            "verified": True,
            "method": "a_record",
            "detail": f"A record points to {SERVER_IP}",
            "cname_target": cname_target,
            "a_records": a_records,
        }

    # --- Not verified ---
    detail_parts = []
    if cname_target:
        detail_parts.append(f"CNAME points to {cname_target} (expected {expected_cname})")
    else:
        detail_parts.append(f"No CNAME record found (expected {expected_cname})")
    if a_records:
        detail_parts.append(f"A records: {', '.join(a_records)} (expected {SERVER_IP})")
    else:
        detail_parts.append(f"No A record found (expected {SERVER_IP})")

    return {
        "verified": False,
        "method": None,
        "detail": " | ".join(detail_parts),
        "cname_target": cname_target,
        "a_records": a_records,
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
