#!/usr/bin/env python3
"""
Delete Hostinger DNS Subdomains (Standalone Script)

This script lists all DNS records and deletes them one by one,
except for those in the WHITELIST array.

No dependencies on other modules - completely standalone.

Usage:
    python scripts/delete_dns_standalone.py [--dry-run]

Examples:
    # Dry run (preview deletions)
    python scripts/delete_dns_standalone.py --dry-run

    # Delete all subdomains except whitelist
    python scripts/delete_dns_standalone.py
"""

import sys
import json
import argparse

# =============================================================================
# CONFIGURATION - Edit these values
# =============================================================================

# Hostinger API Token (get from: hPanel → Profile → API → Generate new token)
API_TOKEN = "womcX8Aw9kRVfNkwJ68PUbRgi7Dg9jL3FKAxdoBv7b7c5f07"

# Base domain
BASE_DOMAIN = "dreambigwithai.com"

# Server IP (for reference)
SERVER_IP = "195.200.14.37"

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


# =============================================================================
# API Functions (using only standard library + requests)
# =============================================================================

def make_request(endpoint, method="GET", data=None):
    """
    Make HTTP request to Hostinger API.
    
    Args:
        endpoint: API endpoint (e.g., "/zones/dreambigwithai.com")
        method: HTTP method (GET, PUT, DELETE)
        data: JSON data for PUT requests
    
    Returns:
        Response dict or None on error
    """
    try:
        import requests
    except ImportError:
        print("Error: 'requests' module not found. Install with: pip install requests")
        sys.exit(1)
    
    base_url = "https://developers.hostinger.com/api/dns/v1"
    url = f"{base_url}{endpoint}"
    
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data, timeout=30)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers, timeout=30)
        else:
            print(f"Error: Unknown method {method}")
            return None
        
        return response
    
    except Exception as e:
        print(f"Request error: {e}")
        return None


def list_dns_records(domain):
    """
    List all DNS records for a domain.
    
    Args:
        domain: Base domain (e.g., "dreambigwithai.com")
    
    Returns:
        List of record dicts or None on error
    """
    response = make_request(f"/zones/{domain}")
    
    if response is None:
        return None
    
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 401:
        print("Error: Invalid or expired API token")
        return None
    elif response.status_code == 404:
        print(f"Error: Domain '{domain}' not found in your account")
        return None
    else:
        print(f"Error: API returned HTTP {response.status_code}")
        try:
            error = response.json()
            print(f"  Details: {error}")
        except:
            pass
        return None


def delete_subdomain(domain, subdomain, current_records=None):
    """
    Delete a subdomain's DNS records using DELETE with filters.
    
    Args:
        domain: Base domain (e.g., "dreambigwithai.com")
        subdomain: Subdomain name to delete (e.g., "cryptoprice")
        current_records: Not used (kept for compatibility)
    
    Returns:
        True if successful, False otherwise
    """
    import http.client
    import json
    
    try:
        conn = http.client.HTTPSConnection("developers.hostinger.com")
        payload = json.dumps({"filters": [{"name": subdomain, "type": "A"}]})
        
        conn.request("DELETE", f"/api/dns/v1/zones/{domain}", payload, {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_TOKEN}"
        })
        
        res = conn.getresponse()
        data = res.read()
        
        if res.status == 200:
            return True
        else:
            print(f"  Error: HTTP {res.status}")
            print(f"  Details: {data.decode('utf-8')[:200]}")
            return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


# =============================================================================
# Helper Functions
# =============================================================================

def is_whitelisted(subdomain):
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


def print_banner():
    """Print script banner."""
    print("=" * 80)
    print("HOSTINGER DNS CLEANUP SCRIPT (Standalone)")
    print("=" * 80)
    print(f"Domain: {BASE_DOMAIN}")
    print(f"API Token: {'*' * 20}...{API_TOKEN[-10:] if len(API_TOKEN) > 10 else '(not set)'}")
    print(f"Whitelist: {len(WHITELIST)} entries")
    print("=" * 80)


# =============================================================================
# Main Logic
# =============================================================================

def bulk_delete_subdomains(domain, filters_list):
    """
    Delete multiple subdomains using DELETE with filters (efficient bulk delete).
    
    Args:
        domain: Base domain (e.g., "dreambigwithai.com")
        filters_list: List of {"name": subdomain, "type": "A"} dicts
    
    Returns:
        True if successful, False otherwise
    """
    import http.client
    import json
    
    try:
        conn = http.client.HTTPSConnection("developers.hostinger.com")
        payload = json.dumps({"filters": filters_list})
        
        conn.request("DELETE", f"/api/dns/v1/zones/{domain}", payload, {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_TOKEN}"
        })
        
        res = conn.getresponse()
        data = res.read()
        
        if res.status == 200:
            return True
        else:
            print(f"  Error: HTTP {res.status}")
            print(f"  Details: {data.decode('utf-8')[:200]}")
            return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Delete Hostinger DNS subdomains (except whitelist) - Standalone"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview deletions without actually deleting"
    )
    parser.add_argument(
        "--domain",
        default=BASE_DOMAIN,
        help=f"Base domain (default: {BASE_DOMAIN})"
    )
    parser.add_argument(
        "--whitelist",
        nargs="+",
        help="Additional subdomains to whitelist (space-separated)"
    )
    
    args = parser.parse_args()
    
    # Check API token
    if API_TOKEN == "YOUR_HOSTINGER_API_TOKEN_HERE":
        print("Error: Please set your API_TOKEN in the script")
        print("  1. Get token from: hPanel → Profile → API → Generate new token")
        print("  2. Edit this file and update API_TOKEN constant")
        sys.exit(1)
    
    # Add additional whitelist entries
    if args.whitelist:
        WHITELIST.extend(args.whitelist)
        print(f"Added to whitelist: {args.whitelist}")
    
    print_banner()
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        print("")
    
    # Step 1: Fetch all DNS records
    print(f"Fetching DNS records for {args.domain}...")
    records = list_dns_records(args.domain)
    
    if records is None:
        print("Failed to fetch DNS records")
        sys.exit(1)
    
    print(f"Found {len(records)} DNS records")
    print("")
    
    # Step 2: Categorize records
    to_delete = []
    to_keep = []
    
    print("=" * 80)
    print("DNS RECORDS")
    print("=" * 80)
    print(f"{'STATUS':<10} | {'NAME':<30} | {'TYPE':<6} | {'VALUE':<20}")
    print("-" * 80)
    
    for record in records:
        name = record.get("name", "")
        record_type = record.get("type", "")
        
        # Get value
        value = ""
        if record.get("records") and len(record["records"]) > 0:
            value = record["records"][0].get("content", "")
        
        # Check whitelist
        if is_whitelisted(name):
            status = "✓ KEEP"
            to_keep.append(name)
        else:
            status = "✗ DELETE"
            to_delete.append(name)
        
        print(f"{status:<10} | {name:<30} | {record_type:<6} | {value:<20}")
    
    print("=" * 80)
    print("")
    
    # Step 3: Summary
    print("=" * 80)
    print("DELETION PLAN")
    print("=" * 80)
    print(f"Total records:     {len(records)}")
    print(f"Will keep:         {len(to_keep)} (whitelisted)")
    print(f"Will delete:       {len(to_delete)}")
    print("")
    
    if to_keep:
        print("Whitelisted (KEEP):")
        for name in to_keep:
            print(f"  ✓ {name}.{args.domain}")
        print("")
    
    if to_delete:
        print("To be DELETED:")
        for name in to_delete:
            print(f"  ✗ {name}.{args.domain}")
        print("")
    
    # Step 4: Execute or preview
    if args.dry_run:
        print("=" * 80)
        print("🔍 DRY RUN COMPLETE - No changes made")
        print("=" * 80)
        print("")
        print("To actually delete, run without --dry-run flag:")
        print(f"  python {sys.argv[0]}")
        return
    
    # Actual deletion - use bulk delete with filters (A records only)
    print("=" * 80)
    print("🗑️  STARTING BULK DELETION (A records only, keeping MX/TXT/CNAME)")
    print("=" * 80)
    
    # Build filters for non-whitelisted A records only
    filters_list = []
    for record in records:
        name = record.get("name", "")
        rtype = record.get("type", "").upper()
        if rtype == "A" and not is_whitelisted(name):
            filters_list.append({"name": name, "type": "A"})
    
    print(f"Deleting {len(filters_list)} A records in one request...")
    
    if bulk_delete_subdomains(args.domain, filters_list):
        print(f"✓ Successfully deleted {len(filters_list)} A records")
    else:
        print("✗ Bulk deletion failed, trying individual deletions...")
        # Fallback to individual deletions
        deleted = 0
        failed = 0
        for f in filters_list:
            if delete_subdomain(args.domain, f["name"]):
                deleted += 1
            else:
                failed += 1
        print(f"Deleted: {deleted}, Failed: {failed}")
    
    # Final summary
    print("")
    print("=" * 80)
    print("DELETION COMPLETE")
    print("=" * 80)
    print(f"Deleted A records: {len(filters_list)}")
    print(f"Kept (whitelist + non-A): {len(records) - len(filters_list)}")
    print("=" * 80)
    print("")
    print("✅ Done!")
    print("Note: DNS propagation takes 5-60 minutes")


if __name__ == "__main__":
    main()
