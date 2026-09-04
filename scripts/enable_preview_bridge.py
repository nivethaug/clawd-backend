#!/usr/bin/env python3
"""One-time worker script: enable the preview bridge on EXISTING project vhosts.

Patches every nginx frontend vhost (sites-available/*.conf) to inject
    sub_filter '</head>' '<script src=".../preview-bridge.js" defer></script></head>';
into served HTML + `gzip off` in the SPA location, then tests and reloads nginx.

New projects get this automatically from NginxConfigurator.generate_config();
this script covers projects created before that change.

Usage (on the worker VPS):
    python3 scripts/enable_preview_bridge.py            # patch all + reload
    python3 scripts/enable_preview_bridge.py --dry-run  # show what would change
    python3 scripts/enable_preview_bridge.py --domain abc123

Each patched file gets a `.bak-bridge` backup; if `nginx -t` fails after
patching, every backup is restored and nginx is NOT reloaded.
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_CONFIG_DIR = "/etc/nginx/sites-available"
BRIDGE_URL_DEFAULT = "https://api.dreamagent.cloud/preview-bridge.js"

SPA_MARKER = "try_files $uri $uri/ /index.html;"
SUB_FILTER_BLOCK = """
    # DreamAgent preview bridge (injected HTML script for the design layer)
    sub_filter '</head>' '<script src="{url}" defer></script></head>';
    sub_filter_once on;
"""


def patch_config(content: str, bridge_url: str):
    """Return (patched_content, changed). Idempotent."""
    if "sub_filter" in content:
        return content, False
    if SPA_MARKER not in content:
        return content, False  # not a frontend vhost

    patched = content

    # 1. inject sub_filter after `index index.html;`
    inject = SUB_FILTER_BLOCK.format(url=bridge_url)
    patched, n = re.subn(r"(index index\.html;\n)", r"\1" + inject.replace("\\", "\\\\"), patched, count=1)
    if n == 0:
        return content, False

    # 2. `gzip off;` inside the SPA location so sub_filter sees plain HTML
    patched, n = re.subn(r"(location / \{\n)(\s+try_files)", r"\1        gzip off;\n\2", patched, count=1)

    return patched, True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config-dir", default=DEFAULT_CONFIG_DIR)
    ap.add_argument("--domain", help="patch a single project domain (subdomain only)")
    ap.add_argument("--bridge-url", default=BRIDGE_URL_DEFAULT)
    ap.add_argument("--nginx-bin", default="/usr/sbin/nginx")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config_dir = Path(args.config_dir)
    if not config_dir.is_dir():
        print(f"✗ config dir not found: {config_dir}")
        sys.exit(1)

    files = sorted(config_dir.glob("*.conf"))
    if args.domain:
        files = [config_dir / f"{args.domain}.conf"]

    patched_files, backups = [], []
    for f in files:
        if not f.is_file():
            print(f"— missing: {f.name}")
            continue
        content = f.read_text()
        new_content, changed = patch_config(content, args.bridge_url)
        if not changed:
            print(f"— skip (no SPA block or already patched): {f.name}")
            continue
        if args.dry_run:
            print(f"[dry-run] would patch: {f.name}")
            continue
        backup = f.with_suffix(".conf.bak-bridge")
        shutil.copy2(f, backup)
        backups.append((f, backup))
        f.write_text(new_content)
        patched_files.append(f)
        print(f"✓ patched: {f.name} (backup: {backup.name})")

    if args.dry_run:
        print(f"\n[dry-run] {len(patched_files) if not args.dry_run else len(files)} candidate(s) examined; no changes written.")
        return

    if not patched_files:
        print("Nothing to patch.")
        return

    test = subprocess.run([args.nginx_bin, "-t"], capture_output=True, text=True)
    if test.returncode != 0:
        print(f"✗ nginx -t FAILED:\n{test.stderr}")
        print("Rolling back all patches...")
        for f, backup in backups:
            shutil.copy2(backup, f)
            print(f"  restored {f.name}")
        sys.exit(1)

    reload_res = subprocess.run(["/usr/bin/systemctl", "reload", "nginx"], capture_output=True, text=True)
    if reload_res.returncode != 0:
        print(f"✗ nginx reload failed: {reload_res.stderr}")
        sys.exit(1)

    print(f"\n✅ {len(patched_files)} vhost(s) patched and nginx reloaded.")


if __name__ == "__main__":
    main()
