#!/usr/bin/env python3
"""
Generate thumbnails for templates + gallery from deployed site URLs.

Uses Chromium's DevTools Protocol (CDP) on port 9222 to navigate to each
project's deployed URL, wait for render, capture a screenshot, and update
the template/gallery thumbnail_url in the DB.

Runs on the WORKER VPS (where Chromium is).

Usage:
    export API_URL=https://api.dreamagent.cloud
    export AUTH_TOKEN=<token>

    python scripts/generate_thumbnails.py --templates
    python scripts/generate_thumbnails.py --gallery
    python scripts/generate_thumbnails.py --all

Requires: Chromium running on 127.0.0.1:9222 (chrome-devtools.service)
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
import requests

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

API_URL = os.getenv("API_URL", "https://api.dreamagent.cloud").rstrip("/")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
CDP_URL = "http://127.0.0.1:9222"
RENDER_WAIT = 3  # seconds to wait for page to render before screenshot
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800

LOG_DIR = Path(__file__).parent.parent / "logs"
THUMBNAIL_DIR = Path("/root/clawd/public/images")

MAX_RETRIES = 3


# ──────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────

LOG_DIR.mkdir(parents=True, exist_ok=True)
_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
_log_file = LOG_DIR / f"thumbnails_{_ts}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_file, encoding="utf-8"),
    ],
)
log = logging.getLogger("thumbnails")
log.info(f"📋 Log file: {_log_file}")


# ──────────────────────────────────────────────────────────────────────
# CDP screenshot via HTTP
# ──────────────────────────────────────────────────────────────────────


def _cdp_request(method: str, params: dict = None) -> dict:
    """Send a CDP command via HTTP to the running Chromium."""
    # Get the first browser tab's webSocketDebuggerUrl
    resp = httpx.get(f"{CDP_URL}/json/new?about:blank", timeout=10)
    if resp.status_code != 200:
        # Fallback: list existing tabs
        resp = httpx.get(f"{CDP_URL}/json/list", timeout=10)
        tabs = resp.json()
        if not tabs:
            raise RuntimeError("No Chrome tabs available")
        tab = tabs[0]
    else:
        tab = resp.json()

    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("No WebSocket debugger URL from Chrome")

    # For simple commands, use the HTTP /json/protocol endpoint
    # Actually, CDP over HTTP doesn't work for most commands.
    # We need websocket. Let's use a simpler approach: the Page.captureScreenshot
    # via the HTTP endpoint that Chrome provides.
    raise NotImplementedError("CDP requires WebSocket — using subprocess instead")


def capture_screenshot(url: str, output_path: str) -> bool:
    """Capture a screenshot of a URL using Chromium headless.

    Uses the --screenshot flag which is the simplest approach — no CDP needed.
    """
    import subprocess

    cmd = [
        "/usr/bin/chromium",
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}",
        "--screenshot=" + output_path,
        "--virtual-time-budget=5000",  # wait 5s for JS to render
        url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.warning(f"  Chromium returned {result.returncode}: {result.stderr[:200]}")
        return Path(output_path).exists() and Path(output_path).stat().st_size > 0
    except subprocess.TimeoutExpired:
        log.error(f"  Chromium timeout for {url}")
        return False
    except Exception as exc:
        log.error(f"  Chromium error: {exc}")
        return False


# ──────────────────────────────────────────────────────────────────────
# Upload thumbnail
# ──────────────────────────────────────────────────────────────────────


def upload_thumbnail(image_path: str) -> Optional[str]:
    """Upload a thumbnail image to the API and return the URL."""
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    try:
        with open(image_path, "rb") as f:
            files = {"file": (Path(image_path).name, f, "image/png")}
            resp = requests.post(
                f"{API_URL}/gallery/upload-thumbnail",
                headers=headers,
                files=files,
                timeout=30,
            )
        if resp.status_code in (200, 201):
            data = resp.json()
            url = data.get("thumbnail_url", "")
            log.info(f"  Uploaded: {url}")
            return url
        else:
            log.error(f"  Upload failed: HTTP {resp.status_code} {resp.text[:200]}")
            return None
    except Exception as exc:
        log.error(f"  Upload error: {exc}")
        return None


# ──────────────────────────────────────────────────────────────────────
# Update template/gallery thumbnail
# ──────────────────────────────────────────────────────────────────────


def update_template_thumbnail(template_id: int, thumbnail_url: str) -> bool:
    """Update a template's thumbnail_url."""
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.put(
            f"{API_URL}/templates/{template_id}",
            headers=headers,
            json={"thumbnail_url": thumbnail_url},
            timeout=10,
        )
        return resp.status_code in (200, 201)
    except Exception:
        return False


def update_gallery_thumbnail(gallery_id: int, thumbnail_url: str) -> bool:
    """Update a gallery item's thumbnail_url."""
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.put(
            f"{API_URL}/gallery/{gallery_id}",
            headers=headers,
            json={"thumbnail_url": thumbnail_url},
            timeout=10,
        )
        return resp.status_code in (200, 201)
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────
# Main logic
# ──────────────────────────────────────────────────────────────────────


def fetch_templates() -> List[Dict[str, Any]]:
    """Fetch all templates from the API."""
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    resp = requests.get(f"{API_URL}/templates?limit=50", headers=headers, timeout=15)
    if resp.status_code != 200:
        log.error(f"Failed to fetch templates: {resp.status_code}")
        return []
    return resp.json().get("templates", [])


def fetch_gallery() -> List[Dict[str, Any]]:
    """Fetch all gallery items from the API."""
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    resp = requests.get(f"{API_URL}/gallery?limit=50", headers=headers, timeout=15)
    if resp.status_code != 200:
        log.error(f"Failed to fetch gallery: {resp.status_code}")
        return []
    return resp.json().get("projects", [])


def get_project_url(domain: str) -> str:
    """Build the deployed project URL from its domain."""
    return f"https://{domain}.dreamagent.cloud"


def process_items(items: List[Dict], item_type: str, update_fn) -> None:
    """Capture screenshots + upload + update for each item."""
    success = 0
    skipped = 0
    failed = 0

    for i, item in enumerate(items, 1):
        title = item.get("title", f"item-{item.get('id', i)}")
        item_id = item.get("id")
        project_id = item.get("project_id")
        existing_thumb = item.get("thumbnail_url", "")

        # Skip if already has a thumbnail
        if existing_thumb and not existing_thumb.endswith("placeholder"):
            log.info(f"[{i}/{len(items)}] {title} — skipped (has thumbnail)")
            skipped += 1
            continue

        # Get the project's domain → URL
        # We need to fetch the project to get its domain
        headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
        proj_resp = requests.get(f"{API_URL}/projects/{project_id}", headers=headers, timeout=10)
        if proj_resp.status_code != 200:
            log.warning(f"[{i}/{len(items)}] {title} — could not fetch project {project_id}")
            failed += 1
            continue

        project = proj_resp.json()
        domain = project.get("domain", "")
        if not domain:
            log.warning(f"[{i}/{len(items)}] {title} — no domain for project {project_id}")
            failed += 1
            continue

        url = get_project_url(domain)
        log.info(f"[{i}/{len(items)}] {title} → {url}")

        # Capture screenshot
        THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
        screenshot_path = str(THUMBNAIL_DIR / f"thumb_{item_type}_{item_id}.png")

        if capture_screenshot(url, screenshot_path):
            # Upload
            thumb_url = upload_thumbnail(screenshot_path)
            if thumb_url:
                # Update DB
                if update_fn(item_id, thumb_url):
                    log.info(f"  ✅ Thumbnail updated for {title}")
                    success += 1
                else:
                    log.error(f"  ⚠️ Failed to update {item_type} record")
                    failed += 1
            else:
                failed += 1

            # Clean up local screenshot
            Path(screenshot_path).unlink(missing_ok=True)
        else:
            log.error(f"  ⚠️ Screenshot failed for {url}")
            failed += 1

    log.info(f"\n{item_type.title()}: {success} updated, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate thumbnails from deployed site URLs")
    parser.add_argument("--templates", action="store_true", help="Process templates only")
    parser.add_argument("--gallery", action="store_true", help="Process gallery only")
    parser.add_argument("--all", action="store_true", help="Process both (default)")
    parser.add_argument("--force", action="store_true", help="Regenerate even if thumbnail exists")
    args = parser.parse_args()

    if not args.templates and not args.gallery and not args.all:
        args.all = True

    if not AUTH_TOKEN:
        log.error("ERROR: Set AUTH_TOKEN env var")
        sys.exit(1)

    # Verify Chromium is available
    import shutil
    if not shutil.which("chromium"):
        log.error("ERROR: chromium not found. Install: apt install chromium")
        sys.exit(1)

    log.info(f"{'=' * 50}")
    log.info(f"Thumbnail Generator — {datetime.now(timezone.utc).isoformat()}")
    log.info(f"API: {API_URL}")
    log.info(f"{'=' * 50}")

    if args.all or args.templates:
        log.info("\n--- Templates ---")
        templates = fetch_templates()
        if args.force:
            for t in templates:
                t["thumbnail_url"] = ""  # force regeneration
        process_items(templates, "template", update_template_thumbnail)

    if args.all or args.gallery:
        log.info("\n--- Gallery ---")
        gallery = fetch_gallery()
        if args.force:
            for g in gallery:
                g["thumbnail_url"] = ""
        process_items(gallery, "gallery", update_gallery_thumbnail)

    log.info(f"\n{'=' * 50}")
    log.info("DONE")
    log.info(f"{'=' * 50}")
