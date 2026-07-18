#!/usr/bin/env python3
"""
Seed Templates + Gallery for v1.0 Release.

Creates real projects using the DreamAgent API, waits for completion,
then marks them as templates and publishes to gallery.

Features:
  - Resume support (seed_progress.json)
  - Retry with exponential backoff
  - Duplicate protection
  - Configurable polling (env vars)
  - Timestamped logging to logs/
  - Dry-run mode
  - Batch limit (--limit N)
  - Environment validation
  - Detailed final summary

Usage:
    export API_URL=https://api.dreamagent.cloud
    export AUTH_TOKEN=<your_bearer_token>

    python scripts/seed_templates.py --templates           # create templates
    python scripts/seed_templates.py --gallery             # create gallery
    python scripts/seed_templates.py --all                 # both (default)
    python scripts/seed_templates.py --templates --limit 5 # first 5 only
    python scripts/seed_templates.py --templates --dry-run # preview only
    python scripts/seed_templates.py --templates --fresh   # ignore progress

Environment variables:
    API_URL           API base URL (default: https://api.dreamagent.cloud)
    AUTH_TOKEN        Bearer token (required)
    POLL_INTERVAL     Status poll interval in seconds (default: 20)
    PROJECT_TIMEOUT   Max wait per project in seconds (default: 1800)

Each project takes ~5 minutes to generate. 20 templates + 15 gallery = ~35 projects.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

API_URL = os.getenv("API_URL", "https://api.dreamagent.cloud").rstrip("/")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "20"))
PROJECT_TIMEOUT = int(os.getenv("PROJECT_TIMEOUT", "1800"))

MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.5  # seconds, exponential: delay * (RETRY_BASE_DELAY ^ attempt)

# States that mean generation is truly complete
COMPLETED_STATES = frozenset({"ready", "completed", "success"})
# States that mean generation failed
FAILED_STATES = frozenset({"failed", "error"})
# States that mean generation is still in progress
IN_PROGRESS_STATES = frozenset({
    "running", "queued", "generating", "building", "creating",
    "scaffolded", "initializing", "deploying",
})

PROGRESS_FILE = Path(__file__).parent / "seed_progress.json"
LOG_DIR = Path(__file__).parent.parent / "logs"

# ──────────────────────────────────────────────────────────────────────
# Logging setup
# ──────────────────────────────────────────────────────────────────────


def _setup_logging() -> logging.Logger:
    """Configure console + timestamped file logging."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"seed_{ts}.log"

    logger = logging.getLogger("seed")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Console handler — concise INFO
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    # File handler — detailed DEBUG
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    logger.info(f"📋 Log file: {log_file}")
    return logger


log = _setup_logging()


# ──────────────────────────────────────────────────────────────────────
# Progress tracking (resume support)
# ──────────────────────────────────────────────────────────────────────


def _load_progress() -> Dict[str, Any]:
    """Load progress from seed_progress.json."""
    if not PROGRESS_FILE.exists():
        return {"templates": {}, "gallery": {}}
    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        if "templates" not in data:
            data["templates"] = {}
        if "gallery" not in data:
            data["gallery"] = {}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning(f"Could not load progress file: {exc} — starting fresh")
        return {"templates": {}, "gallery": {}}


def _save_progress(progress: Dict[str, Any]) -> None:
    """Save progress to seed_progress.json."""
    try:
        PROGRESS_FILE.write_text(
            json.dumps(progress, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning(f"Could not save progress file: {exc}")


def _is_completed(progress: Dict[str, Any], section: str, name: str) -> bool:
    """Check if an item is already completed in progress."""
    entry = progress.get(section, {}).get(name)
    return entry is not None and entry.get("status") == "completed"


def _mark_completed(
    progress: Dict[str, Any],
    section: str,
    name: str,
    project_id: Optional[int],
    detail: str = "",
) -> None:
    """Record a completed item in progress and save immediately."""
    progress.setdefault(section, {})[name] = {
        "status": "completed",
        "project_id": project_id,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
    }
    _save_progress(progress)


# ──────────────────────────────────────────────────────────────────────
# HTTP retry helper
# ──────────────────────────────────────────────────────────────────────


def _request(
    method: str,
    url: str,
    *,
    headers: Optional[dict] = None,
    json_body: Optional[dict] = None,
    timeout: int = 30,
) -> Optional[requests.Response]:
    """Make an HTTP request with exponential backoff retry.

    Retries on: connection errors, timeouts, HTTP 500+, and Cloudflare
    transient errors (502, 503, 504, 520-526).

    Returns the Response on success, or None if all retries are exhausted.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=timeout,
            )

            # Retry on server errors and Cloudflare transient codes
            if resp.status_code >= 500 or resp.status_code in (408, 429):
                delay = min(RETRY_BASE_DELAY ** attempt, 30)
                log.debug(
                    f"  ↻ Retry {attempt}/{MAX_RETRIES}: HTTP {resp.status_code} "
                    f"from {method} {url} — waiting {delay:.1f}s"
                )
                if attempt < MAX_RETRIES:
                    time.sleep(delay)
                    continue

            return resp

        except (requests.ConnectionError, requests.Timeout) as exc:
            delay = min(RETRY_BASE_DELAY ** attempt, 30)
            log.debug(
                f"  ↻ Retry {attempt}/{MAX_RETRIES}: {type(exc).__name__} "
                f"on {method} {url} — waiting {delay:.1f}s"
            )
            if attempt < MAX_RETRIES:
                time.sleep(delay)
                continue

        except requests.RequestException as exc:
            log.error(f"  ❌ Request failed: {exc}")
            return None

    log.error(f"  ❌ All {MAX_RETRIES} retries exhausted for {method} {url}")
    return None


def _ok(resp: Optional[requests.Response]) -> bool:
    """Check if a response is successful (200 or 201)."""
    return resp is not None and resp.status_code in (200, 201)


# ──────────────────────────────────────────────────────────────────────
# Template definitions (unchanged from original)
# ──────────────────────────────────────────────────────────────────────

TEMPLATES: List[Dict[str, Any]] = [
    # ── Website (10) ─────────────────────────────────────────────
    {
        "name": "SaaS Landing Page",
        "type_id": 1,
        "category": "Website",
        "description": "A premium SaaS landing page for a fictional product called 'FlowAnalytics'. Include a hero section with gradient background and CTA button, feature grid with icons (3-4 features), pricing table with 3 tiers, testimonials carousel, and footer with social links. Modern, clean design inspired by Linear and Vercel. Dark theme with accent color.",
        "featured": True,
    },
    {
        "name": "Developer Portfolio",
        "type_id": 1,
        "category": "Website",
        "description": "A minimalist developer portfolio with a hero section showing name + role, projects grid with hover cards, about section with skills, and a contact form. Clean typography, lots of whitespace, subtle animations on scroll. Light theme with dark accent.",
        "featured": True,
    },
    {
        "name": "Business Website",
        "type_id": 1,
        "category": "Website",
        "description": "A professional business website for a consulting firm. Include a hero with company tagline, services section with 4 cards, about us with team photos placeholder, case studies section, and contact form with map placeholder. Corporate blue color scheme, trustworthy and professional.",
        "featured": False,
    },
    {
        "name": "E-commerce Store",
        "type_id": 1,
        "category": "Website",
        "description": "A modern e-commerce storefront for a boutique coffee brand. Product grid with add-to-cart buttons, product detail modal, shopping cart sidebar, and checkout form. Warm earth tones, premium feel, product photography placeholders.",
        "featured": True,
    },
    {
        "name": "Documentation Site",
        "type_id": 1,
        "category": "Website",
        "description": "A clean documentation site with a sidebar navigation, main content area with code blocks, search bar, and version switcher. Inspired by Stripe docs. Dark sidebar, light content area, syntax-highlighted code blocks.",
        "featured": False,
    },
    {
        "name": "Personal Blog",
        "type_id": 1,
        "category": "Website",
        "description": "A personal blog with a featured post hero, post grid with categories, individual post page with reading time, and an about sidebar. Warm, readable typography with a focus on content. Magazine-style layout.",
        "featured": False,
    },
    {
        "name": "Startup Coming Soon",
        "type_id": 1,
        "category": "Website",
        "description": "A captivating 'coming soon' landing page for a tech startup. Include an animated hero with countdown timer, email capture form with notification, social media links, and a minimal feature teaser. Gradient background with glassmorphism card. Dark theme with vibrant accent.",
        "featured": False,
    },
    {
        "name": "Event Landing",
        "type_id": 1,
        "category": "Website",
        "description": "An event landing page for a tech conference. Include hero with event date + location, speaker grid with photos and bios, schedule timeline, sponsor logos, and registration form with ticket tiers. Bold, energetic design with a focus on urgency.",
        "featured": False,
    },
    {
        "name": "Podcast Website",
        "type_id": 1,
        "category": "Website",
        "description": "A podcast website with a featured latest episode player, episode list with play buttons, host bios, subscribe links (Apple, Spotify, Google), and a contact form. Warm, audio-focused design with waveform visuals.",
        "featured": False,
    },
    {
        "name": "Non-Profit Website",
        "type_id": 1,
        "category": "Website",
        "description": "A non-profit organization website with a mission hero, impact statistics counters, programs section with images, donation form with progress bar, volunteer signup, and stories section. Warm, hopeful design with a focus on community.",
        "featured": False,
    },
    # ── Telegram, Discord, Scheduler templates — add tomorrow ──
    # The script will skip these types if they're not in the list.
    # To add them, append entries with type_id 2 (Telegram), 3 (Discord), 5 (Scheduler).
]

# ──────────────────────────────────────────────────────────────────────
# Gallery definitions (unchanged from original)
# ──────────────────────────────────────────────────────────────────────

GALLERY: List[Dict[str, Any]] = [
    {"name": "CRM Dashboard", "type_id": 1, "description": "A modern CRM dashboard with contact management, deal pipeline (kanban), activity timeline, and sales metrics. Drag-and-drop deals between stages. Premium dark UI with data tables and charts."},
    {"name": "Restaurant Website", "type_id": 1, "description": "An elegant restaurant website with a full-screen hero image, menu cards with prices, reservation form, photo gallery, and location map. Warm, appetizing design with elegant typography."},
    {"name": "Gym Fitness", "type_id": 1, "description": "A high-energy gym website with bold hero section, class schedule table, trainer cards, membership pricing tiers, and a BMI calculator widget. Dark theme with neon accents, motivational imagery."},
    {"name": "Analytics Dashboard", "type_id": 1, "description": "A web analytics dashboard with traffic sources, visitor map, conversion funnel, top pages, and real-time active users. Data-dense but clean, inspired by Plausible Analytics."},
    {"name": "AI Chat Interface", "type_id": 1, "description": "A sleek AI chat interface with conversation history sidebar, streaming message display, model selector, and code block syntax highlighting. Dark theme inspired by ChatGPT."},
    {"name": "Booking System", "type_id": 1, "description": "An appointment booking system with calendar view, time slot selection, service menu, booking confirmation, and reminder settings. Clean, trustworthy design with clear CTAs."},
    {"name": "Invoice System", "type_id": 1, "description": "An invoicing system with invoice list, create-invoice form with line items, PDF preview, payment status tracking, and client management. Professional, clean design with print-ready invoices."},
    {"name": "Crypto Dashboard", "type_id": 1, "description": "A real-time crypto tracking dashboard with price tickers, portfolio allocation pie chart, recent transactions, and price alerts setup. Dark theme with green/red price indicators."},
    {"name": "Agency Website", "type_id": 1, "description": "A creative agency website with portfolio grid, services with hover effects, team bios, client logos carousel, and a contact form with project type selector. Bold, modern design with smooth animations."},
    {"name": "Real Estate Listings", "type_id": 1, "description": "A real estate listing site with property search filters, map view, property cards with photos, detail page with gallery, and agent contact form. Clean, aspirational design."},
]


# ──────────────────────────────────────────────────────────────────────
# Environment validation
# ──────────────────────────────────────────────────────────────────────


def validate_environment() -> bool:
    """Validate API_URL, AUTH_TOKEN, and key endpoints before starting."""
    if not AUTH_TOKEN:
        log.error("❌ AUTH_TOKEN is not set. Export it: export AUTH_TOKEN=<token>")
        return False

    headers = {"Authorization": f"Bearer {AUTH_TOKEN}", "Content-Type": "application/json"}

    # 1. Check API reachable
    log.info(f"🔍 Validating environment: {API_URL}")
    resp = _request("GET", f"{API_URL}/project-types", headers=headers, timeout=15)
    if resp is None:
        log.error("❌ API is not reachable. Check API_URL and network.")
        return False
    if resp.status_code == 401:
        log.error("❌ AUTH_TOKEN is invalid or expired. Get a fresh token.")
        return False
    if resp.status_code not in (200, 201):
        log.error(f"❌ Unexpected response from API: HTTP {resp.status_code}")
        return False

    # 2. Check key endpoints respond
    endpoints_ok = True
    for endpoint in ["/templates/my-templates", "/gallery/my-published"]:
        resp = _request("GET", f"{API_URL}{endpoint}", headers=headers, timeout=15)
        if resp is None or resp.status_code not in (200, 201, 404):
            log.warning(f"⚠️ Endpoint {endpoint} returned HTTP {resp.status_code if resp else 'None'}")
            endpoints_ok = False

    if endpoints_ok:
        log.info("✅ Environment validated — API reachable, auth valid, endpoints responding")
    else:
        log.warning("⚠️ Some endpoints returned unexpected status — continuing anyway")

    return True


# ──────────────────────────────────────────────────────────────────────
# Duplicate protection
# ──────────────────────────────────────────────────────────────────────


def _check_existing_templates() -> set[str]:
    """Fetch existing template titles to prevent duplicates."""
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    resp = _request("GET", f"{API_URL}/templates/my-templates", headers=headers, timeout=15)
    if resp is None or resp.status_code not in (200, 201):
        log.debug("  Could not fetch existing templates — duplicate check disabled")
        return set()
    try:
        data = resp.json()
        items = data.get("templates", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        titles = set()
        for t in items:
            if isinstance(t, dict):
                titles.add(t.get("title", ""))
            elif isinstance(t, str):
                titles.add(t)
        log.debug(f"  Found {len(titles)} existing templates")
        return titles
    except (json.JSONDecodeError, KeyError, TypeError):
        return set()


def _check_existing_gallery() -> set[str]:
    """Fetch existing gallery titles to prevent duplicates."""
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    resp = _request("GET", f"{API_URL}/gallery/my-published", headers=headers, timeout=15)
    if resp is None or resp.status_code not in (200, 201):
        log.debug("  Could not fetch existing gallery — duplicate check disabled")
        return set()
    try:
        data = resp.json()
        items = data.get("gallery_projects", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        titles = set()
        for g in items:
            if isinstance(g, dict):
                titles.add(g.get("title", ""))
            elif isinstance(g, str):
                titles.add(g)
        log.debug(f"  Found {len(titles)} existing gallery items")
        return titles
    except (json.JSONDecodeError, KeyError, TypeError):
        return set()


# ──────────────────────────────────────────────────────────────────────
# Core API operations
# ──────────────────────────────────────────────────────────────────────


def _headers() -> dict:
    return {"Authorization": f"Bearer {AUTH_TOKEN}", "Content-Type": "application/json"}


def create_project(name: str, description: str, type_id: int) -> Optional[dict]:
    """Create a project via the API. Returns project dict or None.

    Handles 409 (another creation in progress) by waiting and retrying up to
    PROJECT_TIMEOUT seconds — the API enforces one creation at a time per user.
    """
    start = time.time()
    while time.time() - start < PROJECT_TIMEOUT:
        resp = _request(
            "POST",
            f"{API_URL}/projects",
            headers=_headers(),
            json_body={"name": name, "description": description, "type_id": type_id},
            timeout=30,
        )
        if resp is None:
            return None
        if resp.status_code == 402:
            log.error("  ❌ BLOCKED: insufficient credits. Buy credits and retry.")
            return None
        if resp.status_code == 409:
            # Another project is still creating — wait and retry
            elapsed = int(time.time() - start)
            if elapsed % 60 == 0 and elapsed > 0:
                log.info(f"  ⏳ Waiting for previous creation to finish ({elapsed}s)...")
            time.sleep(POLL_INTERVAL)
            continue
        if resp.status_code not in (200, 201):
            log.error(f"  ❌ Error {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()

    log.error(f"  ⏰ Timed out waiting for previous creation to finish")
    return None


def wait_for_completion(project_id: int) -> str:
    """Poll project status until truly complete, failed, or timeout.

    Returns: 'completed' | 'failed' | 'timeout'
    """
    start = time.time()
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}

    while time.time() - start < PROJECT_TIMEOUT:
        resp = _request(
            "GET",
            f"{API_URL}/projects/{project_id}/status",
            headers=headers,
            timeout=15,
        )
        if resp is not None and resp.status_code in (200, 201):
            status = resp.json().get("status", "unknown").lower()
            elapsed = int(time.time() - start)

            if status in COMPLETED_STATES:
                log.info(f"  ✅ Completed ({status}) in {elapsed}s")
                log.debug(f"  Final status: {status}")
                return "completed"

            if status in FAILED_STATES:
                log.error(f"  ❌ Failed ({status}) after {elapsed}s")
                return "failed"

            # Still in progress — log periodically
            if elapsed > 0 and elapsed % 60 == 0:
                log.info(f"  ⏳ Still '{status}' after {elapsed}s...")

        time.sleep(POLL_INTERVAL)

    log.error(f"  ⏰ Timeout after {int(time.time() - start)}s")
    return "timeout"


def mark_as_template(project_id: int, title: str, category: str, featured: bool) -> bool:
    """Mark a completed project as a template."""
    resp = _request(
        "POST",
        f"{API_URL}/projects/{project_id}/mark-as-template",
        headers=_headers(),
        json_body={
            "title": title,
            "description": f"Template: {title}",
            "category": category,
            "is_featured": featured,
        },
        timeout=15,
    )
    return _ok(resp)


def publish_to_gallery(project_id: int, title: str, description: str, featured: bool) -> bool:
    """Publish a completed project to the gallery."""
    resp = _request(
        "POST",
        f"{API_URL}/projects/{project_id}/publish-to-gallery",
        headers=_headers(),
        json_body={
            "title": title,
            "description": description,
            "is_featured": featured,
        },
        timeout=15,
    )
    return _ok(resp)


# ──────────────────────────────────────────────────────────────────────
# Result tracking for final summary
# ──────────────────────────────────────────────────────────────────────


class RunStats:
    """Tracks outcomes for the final summary."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.created: int = 0
        self.skipped: int = 0
        self.failed: int = 0
        self.timeout: int = 0
        self.already_exists: int = 0
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    @property
    def duration(self) -> str:
        secs = int(self.end_time - self.start_time)
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m {secs % 60}s"

    def summary(self) -> str:
        total = self.created + self.skipped + self.failed + self.timeout + self.already_exists
        return (
            f"\n{self.label}\n"
            f"{'─' * len(self.label)}\n"
            f"  Created:       {self.created}\n"
            f"  Skipped:       {self.skipped}\n"
            f"  Failed:        {self.failed}\n"
            f"  Timeout:       {self.timeout}\n"
            f"  Already Exists:{self.already_exists}\n"
            f"  Total:         {total}\n"
            f"  Duration:      {self.duration}\n"
        )


# ──────────────────────────────────────────────────────────────────────
# Main runners
# ──────────────────────────────────────────────────────────────────────


def run_templates(
    progress: Dict[str, Any],
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> RunStats:
    """Create all template projects with resume + duplicate protection."""
    stats = RunStats("Templates")
    stats.start_time = time.time()

    items = TEMPLATES
    if limit:
        items = items[:limit]

    existing = _check_existing_templates() if not dry_run else set()

    if dry_run:
        log.info(f"\n{'=' * 60}")
        log.info(f"DRY RUN — Templates ({len(items)} items)")
        log.info(f"{'=' * 60}")
        for i, tmpl in enumerate(items, 1):
            log.info(f"  [{i}/{len(items)}] {tmpl['name']} ({tmpl['category']}) featured={tmpl.get('featured', False)}")
        stats.end_time = time.time()
        return stats

    log.info(f"\n{'=' * 60}")
    log.info(f"CREATE TEMPLATES ({len(items)} items, poll={POLL_INTERVAL}s, timeout={PROJECT_TIMEOUT}s)")
    log.info(f"{'=' * 60}")

    for i, tmpl in enumerate(items, 1):
        name = tmpl["name"]
        log.info(f"\n[{i}/{len(items)}] {name} ({tmpl['category']})")

        # Resume check
        if _is_completed(progress, "templates", name):
            log.info(f"  ⏭️ Skipped (already in progress file)")
            stats.skipped += 1
            continue

        # Duplicate check
        if name in existing:
            log.info(f"  ⏭️ Skipped (already exists on server)")
            _mark_completed(progress, "templates", name, None, "already exists")
            stats.already_exists += 1
            continue

        # Create + wait + mark
        project = create_project(name, tmpl["description"], tmpl["type_id"])
        if not project:
            stats.failed += 1
            continue

        pid = project.get("id")
        log.info(f"  Created project {pid}, waiting for completion...")
        log.debug(f"  Project response: {json.dumps(project)[:200]}")

        status = wait_for_completion(pid)
        if status == "completed":
            ok = mark_as_template(pid, name, tmpl["category"], tmpl.get("featured", False))
            if ok:
                log.info(f"  📋 Marked as template")
                _mark_completed(progress, "templates", name, pid, "template published")
                stats.created += 1
            else:
                log.error(f"  ⚠️ Failed to mark as template")
                stats.failed += 1
        elif status == "timeout":
            stats.timeout += 1
        else:
            stats.failed += 1

    stats.end_time = time.time()
    return stats


def run_gallery(
    progress: Dict[str, Any],
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> RunStats:
    """Create all gallery projects with resume + duplicate protection."""
    stats = RunStats("Gallery")
    stats.start_time = time.time()

    items = GALLERY
    if limit:
        items = items[:limit]

    existing = _check_existing_gallery() if not dry_run else set()

    if dry_run:
        log.info(f"\n{'=' * 60}")
        log.info(f"DRY RUN — Gallery ({len(items)} items)")
        log.info(f"{'=' * 60}")
        for i, item in enumerate(items, 1):
            log.info(f"  [{i}/{len(items)}] {item['name']}")
        stats.end_time = time.time()
        return stats

    log.info(f"\n{'=' * 60}")
    log.info(f"CREATE GALLERY ({len(items)} items, poll={POLL_INTERVAL}s, timeout={PROJECT_TIMEOUT}s)")
    log.info(f"{'=' * 60}")

    for i, item in enumerate(items, 1):
        name = item["name"]
        log.info(f"\n[{i}/{len(items)}] {name}")

        # Resume check
        if _is_completed(progress, "gallery", name):
            log.info(f"  ⏭️ Skipped (already in progress file)")
            stats.skipped += 1
            continue

        # Duplicate check
        if name in existing:
            log.info(f"  ⏭️ Skipped (already exists on server)")
            _mark_completed(progress, "gallery", name, None, "already exists")
            stats.already_exists += 1
            continue

        # Create + wait + publish
        project = create_project(name, item["description"], item["type_id"])
        if not project:
            stats.failed += 1
            continue

        pid = project.get("id")
        log.info(f"  Created project {pid}, waiting for completion...")
        log.debug(f"  Project response: {json.dumps(project)[:200]}")

        status = wait_for_completion(pid)
        if status == "completed":
            ok = publish_to_gallery(pid, name, item["description"], i <= 5)
            if ok:
                log.info(f"  🖼️ Published to gallery")
                _mark_completed(progress, "gallery", name, pid, "gallery published")
                stats.created += 1
            else:
                log.error(f"  ⚠️ Failed to publish to gallery")
                stats.failed += 1
        elif status == "timeout":
            stats.timeout += 1
        else:
            stats.failed += 1

    stats.end_time = time.time()
    return stats


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed templates + gallery for v1.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/seed_templates.py --templates\n"
            "  python scripts/seed_templates.py --gallery --limit 5\n"
            "  python scripts/seed_templates.py --all --dry-run\n"
            "  python scripts/seed_templates.py --templates --fresh\n"
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--templates", action="store_true", help="Create templates only")
    mode.add_argument("--gallery", action="store_true", help="Create gallery only")
    mode.add_argument("--all", action="store_true", help="Create both (default)")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N items")
    parser.add_argument("--dry-run", action="store_true", help="Preview without calling API")
    parser.add_argument("--fresh", action="store_true", help="Ignore previous progress (no resume)")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from progress (default)")
    args = parser.parse_args()

    # Default to --all if no mode specified
    if not args.templates and not args.gallery and not args.all:
        args.all = True

    overall_start = time.time()

    log.info(f"{'=' * 60}")
    log.info(f"DreamAgent Seed Script — {datetime.now(timezone.utc).isoformat()}")
    log.info(f"API: {API_URL}")
    log.info(f"Poll: {POLL_INTERVAL}s  Timeout: {PROJECT_TIMEOUT}s  Retries: {MAX_RETRIES}")
    log.info(f"Mode: {'templates' if args.templates else 'gallery' if args.gallery else 'all'}"
             f"{' (dry-run)' if args.dry_run else ''}"
             f"{' (fresh)' if args.fresh else ' (resume)'}")
    log.info(f"{'=' * 60}")

    # Environment validation (skip for dry-run)
    if not args.dry_run:
        if not validate_environment():
            log.error("Environment validation failed. Exiting.")
            sys.exit(1)

    # Load or reset progress
    if args.fresh:
        progress: Dict[str, Any] = {"templates": {}, "gallery": {}}
        _save_progress(progress)
        log.info("📂 Started fresh (progress file reset)")
    else:
        progress = _load_progress()
        completed_t = len(progress.get("templates", {}))
        completed_g = len(progress.get("gallery", {}))
        if completed_t or completed_g:
            log.info(f"📂 Resuming: {completed_t} templates + {completed_g} gallery already done")

    # Run
    all_stats: List[RunStats] = []
    if args.all or args.templates:
        all_stats.append(run_templates(progress, args.limit, args.dry_run))
    if args.all or args.gallery:
        all_stats.append(run_gallery(progress, args.limit, args.dry_run))

    # Final summary
    overall_end = time.time()
    overall_secs = int(overall_end - overall_start)
    overall_str = f"{overall_secs}s" if overall_secs < 60 else f"{overall_secs // 60}m {overall_secs % 60}s"

    log.info(f"\n{'=' * 60}")
    log.info("FINAL SUMMARY")
    log.info(f"{'=' * 60}")
    for s in all_stats:
        log.info(s.summary())
    log.info(f"Overall runtime: {overall_str}")
    log.info(f"Progress file: {PROGRESS_FILE}")
    log.info(f"{'=' * 60}")
