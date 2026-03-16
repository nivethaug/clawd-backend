#!/usr/bin/env python3
"""
Delete Hostinger DNS Subdomains (Except Whitelist)

This script lists all DNS records and deletes them one by one,
except for those in the WHITELIST array.

Usage:
    python scripts/delete_hostinger_dns.py [--domain DOMAIN] [--dry-run]

Examples:
    # Dry run (preview deletions)
    python scripts/delete_hostinger_dns.py --dry-run

    # Delete all subdomains except whitelist
    python scripts/delete_hostinger_dns.py

    # Delete from specific domain
    python scripts/delete_hostinger_dns.py --domain example.com
"""

import sys
import os
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import dns_manager
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# WHITELIST - Subdomains to KEEP (will NOT be deleted)
# =============================================================================

# System/infrastructure subdomains that should NEVER be deleted
WHITELIST = [
    "@",           # Root domain (dreambigwithai.com)
    "www",         # www.dreambigwithai.com
    "mail",        # Mail server
    "ftp",         # FTP server
    "localhost",   # Localhost
    "api",         # Main API server
    "admin",       # Admin panel
    "staging",     # Staging environment
    "dev",         # Development environment
    "test",        # Test environment
    # Protected production subdomains
    "esignpilot",  # esignpilot.dreambigwithai.com
    "salesdocpilot", # salesdocpilot.dreambigwithai.com
    "botpilot",    # botpilot.dreambigwithai.com
    "calmcrypto",  # calmcrypto.dreambigwithai.com
    "promptcraft", # promptcraft.dreambigwithai.com
    # Add more protected subdomains here
]

# Subdomain patterns to keep (partial matches)
WHITELIST_PATTERNS = [
    # Example: Keep all subdomains containing "admin"
    # "admin",
]

# Base domain
BASE_DOMAIN = "dreambigwithai.com"


def is_whitelisted(subdomain: str) -> bool:
    """
    Check if subdomain is in whitelist.
    
    Args:
        subdomain: Subdomain name (e.g., "www", "api")
    
    Returns:
        True if whitelisted (should NOT be deleted)
    """
    # Check exact match
    if subdomain.lower() in [w.lower() for w in WHITELIST]:
        return True
    
    # Check pattern match
    for pattern in WHITELIST_PATTERNS:
        if pattern.lower() in subdomain.lower():
            return True
    
    return False


def list_all_subdomains(domain: str) -> list:
    """
    List all DNS subdomains for a domain.
    
    Args:
        domain: Base domain (e.g., "dreambigwithai.com")
    
    Returns:
        List of subdomain names
    """
    logger.info(f"Fetching DNS records for {domain}...")
    
    result = dns_manager.list_dns_records(domain)
    
    if not result.get("success"):
        logger.error(f"Failed to fetch DNS records: {result.get('error')}")
        return []
    
    records = result.get("records", [])
    subdomains = []
    
    logger.info(f"Found {len(records)} DNS records")
    logger.info("=" * 80)
    
    for record in records:
        name = record.get("name", "")
        record_type = record.get("type", "")
        ttl = record.get("ttl", 0)
        
        # Get the value/content
        value = ""
        if record.get("records") and len(record["records"]) > 0:
            value = record["records"][0].get("content", "")
        
        subdomains.append({
            "name": name,
            "type": record_type,
            "value": value,
            "ttl": ttl
        })
        
        # Display record
        whitelist_status = "✓ KEEP" if is_whitelisted(name) else "✗ DELETE"
        logger.info(f"{whitelist_status:10} | {name:30} | {record_type:6} | {value:20} | TTL: {ttl}")
    
    logger.info("=" * 80)
    
    return subdomains


def delete_subdomains(domain: str, subdomains: list, dry_run: bool = True) -> dict:
    """
    Delete subdomains (except whitelisted ones).
    
    Args:
        domain: Base domain (e.g., "dreambigwithai.com")
        subdomains: List of subdomain dicts
        dry_run: If True, only preview (don't actually delete)
    
    Returns:
        Dict with deletion results
    """
    results = {
        "total": len(subdomains),
        "kept": 0,
        "deleted": 0,
        "failed": 0,
        "skipped": 0,
        "details": []
    }
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("DELETION PLAN")
    logger.info("=" * 80)
    
    to_delete = []
    to_keep = []
    
    for subdomain in subdomains:
        name = subdomain["name"]
        
        if is_whitelisted(name):
            to_keep.append(name)
            results["kept"] += 1
        else:
            to_delete.append(name)
    
    logger.info(f"Total records:     {results['total']}")
    logger.info(f"Will keep:         {len(to_keep)} (whitelisted)")
    logger.info(f"Will delete:       {len(to_delete)}")
    logger.info(f"Whitelisted:       {', '.join(to_keep) if to_keep else '(none)'}")
    logger.info("")
    
    if dry_run:
        logger.info("🔍 DRY RUN - No changes will be made")
        logger.info("=" * 80)
        logger.info("Subdomains to DELETE:")
        for name in to_delete:
            logger.info(f"  ✗ {name}.{domain}")
        logger.info("")
        logger.info("Subdomains to KEEP (whitelisted):")
        for name in to_keep:
            logger.info(f"  ✓ {name}.{domain}")
        logger.info("")
        logger.info("To actually delete, run without --dry-run flag")
        return results
    
    # ACTUAL DELETION
    logger.info("🗑️  STARTING DELETION")
    logger.info("=" * 80)
    
    for name in to_delete:
        logger.info(f"Deleting {name}.{domain}...")
        
        result = dns_manager.delete_a_record(domain, name)
        
        if result.get("success"):
            logger.info(f"  ✓ Deleted: {name}.{domain}")
            results["deleted"] += 1
            results["details"].append({
                "subdomain": name,
                "status": "deleted",
                "message": result.get("message")
            })
        else:
            logger.error(f"  ✗ Failed: {name}.{domain} - {result.get('error')}")
            results["failed"] += 1
            results["details"].append({
                "subdomain": name,
                "status": "failed",
                "error": result.get("error")
            })
    
    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("DELETION SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total records:     {results['total']}")
    logger.info(f"Kept (whitelist):  {results['kept']}")
    logger.info(f"Deleted:           {results['deleted']}")
    logger.info(f"Failed:            {results['failed']}")
    logger.info("=" * 80)
    
    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Delete Hostinger DNS subdomains (except whitelist)"
    )
    parser.add_argument(
        "--domain",
        default=BASE_DOMAIN,
        help=f"Base domain (default: {BASE_DOMAIN})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview deletions without actually deleting"
    )
    parser.add_argument(
        "--whitelist",
        nargs="+",
        help="Additional subdomains to whitelist (space-separated)"
    )
    
    args = parser.parse_args()
    
    # Add additional whitelist entries
    if args.whitelist:
        WHITELIST.extend(args.whitelist)
        logger.info(f"Added to whitelist: {args.whitelist}")
    
    logger.info("=" * 80)
    logger.info("HOSTINGER DNS CLEANUP SCRIPT")
    logger.info("=" * 80)
    logger.info(f"Domain: {args.domain}")
    logger.info(f"Whitelist: {WHITELIST}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 80)
    
    # Step 1: List all subdomains
    subdomains = list_all_subdomains(args.domain)
    
    if not subdomains:
        logger.warning("No DNS records found")
        return
    
    # Step 2: Delete (or preview deletion)
    results = delete_subdomains(args.domain, subdomains, dry_run=args.dry_run)
    
    if args.dry_run:
        logger.info("")
        logger.info("✅ Dry run complete - no changes made")
    else:
        logger.info("")
        logger.info("✅ Deletion complete")
        logger.info(f"Note: DNS propagation takes 5-60 minutes")


if __name__ == "__main__":
    main()
