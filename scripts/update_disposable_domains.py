#!/usr/bin/env python3
"""Refresh data/disposable_email_domains.txt from the community blocklist.

Run locally (or on the VPS) whenever you want the latest domains:

    python scripts/update_disposable_domains.py

Then commit + deploy as usual (backend restart picks it up on import).
The script never REMOVES the curated extras — those live in
services/email_guard.py:_EXTRA_DOMAINS and survive every refresh.
"""

import re
import sys
import urllib.request
from pathlib import Path

URL = ("https://raw.githubusercontent.com/disposable-email-domains/"
       "disposable-email-domains/main/disposable_email_blocklist.conf")
DEST = Path(__file__).resolve().parent.parent / "data" / "disposable_email_domains.txt"


def main() -> int:
    print(f"Downloading {URL} ...")
    with urllib.request.urlopen(URL, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    lines = raw.splitlines()
    domains = sorted({
        line.strip().lower()
        for line in lines
        if line.strip()
        and not line.startswith("#")
        and "." in line
        and re.match(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$", line.strip().lower())
    })

    old = set(DEST.read_text(encoding="utf-8").splitlines()) if DEST.exists() else set()
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text("\n".join(domains) + "\n", encoding="utf-8")

    added = len(set(domains) - old)
    removed = len(old - set(domains))
    print(f"Wrote {len(domains)} domains to {DEST}")
    print(f"  new: {added}, removed: {removed} (refetch is authoritative)")
    print("Commit + `pm2 restart` to activate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
