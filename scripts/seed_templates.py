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
    # ── Website (10) — premium, immersive descriptions following Prompt Builder standards ──
    {
        "name": "SaaS Landing Page",
        "type_id": 1,
        "category": "Website",
        "description": "Build a premium SaaS landing page for 'FlowAnalytics,' a real-time analytics startup. The experience should feel like stepping into a control room — dark cinematic hero with live-updating metric cards, glassmorphism feature panels that glow on hover, pricing tiers presented as holographic cards, and testimonials that slide in with depth. Deep indigo and electric blue palette. Inspired by Linear, Vercel, and Stripe's premium marketing. Clean, confident, and futuristic.",
        "featured": True,
    },
    {
        "name": "Developer Portfolio",
        "type_id": 1,
        "category": "Website",
        "description": "Create an immersive developer portfolio that feels like a personal command center. Hero section with a typing animation cycling through roles, projects displayed as interactive 3D hover cards with glow effects, skills visualized as an animated radar chart, and a contact form that feels like sending a transmission. Light theme with terminal-green accents, monospace details, and subtle particle effects. Inspired by Brittany Chiang and primevue portfolios.",
        "featured": True,
    },
    {
        "name": "Business Website",
        "type_id": 1,
        "category": "Website",
        "description": "Build a corporate consulting website that radiates trust and sophistication. Full-screen hero with parallax cityscape, services presented as premium accordions with smooth slide reveals, case studies as cinematic cards with before/after metrics, team section with elegant hover-reveal bios, and a contact form with map integration. Deep navy blue and gold accents. Inspired by McKinsey and BCG's premium digital presence.",
        "featured": False,
    },
    {
        "name": "E-commerce Store",
        "type_id": 1,
        "category": "Website",
        "description": "Create a boutique coffee brand storefront that feels like a luxury sensory experience. Cinematic hero with steam animation rising from a cup, product grid where each card tilts in 3D on hover with aroma description overlays, shopping cart that slides in as a premium drawer, and checkout with single-page flow. Warm earth tones, gold accents, product photography with depth-of-field blur. Inspired by Blue Bottle and Stumptown's premium e-commerce.",
        "featured": True,
    },
    {
        "name": "Documentation Site",
        "type_id": 1,
        "category": "Website",
        "description": "Build a developer documentation hub that feels like a premium IDE. Dark sidebar with tree-view navigation and search, main content with syntax-highlighted code blocks that have copy buttons and line numbers, interactive API playground with live request/response, and a version switcher that smoothly transitions content. Split-screen layout, dark sidebar with light content. Inspired by Stripe Docs, Linear Docs, and Mintlify.",
        "featured": False,
    },
    {
        "name": "Personal Blog",
        "type_id": 1,
        "category": "Website",
        "description": "Create a personal blog that feels like a premium digital magazine. Featured article hero with full-bleed image and elegant overlay text, article grid with magazine-style masonry layout, reading view with elegant serif typography and estimated read time, and an about sidebar with animated skill bars. Warm sepia tones with cream backgrounds. Inspired by Medium's premium publications and Ghost themes.",
        "featured": False,
    },
    {
        "name": "Startup Coming Soon",
        "type_id": 1,
        "category": "Website",
        "description": "Build a captivating 'coming soon' experience for 'Nexus AI,' a generative AI startup. Animated hero with particle network background that responds to mouse movement, countdown timer with smooth flip animations, email capture form that glows on focus and shows success confetti, and minimal feature teasers that fade in on scroll. Deep space gradient (purple to black) with neon cyan accents. Glassmorphism cards throughout.",
        "featured": False,
    },
    {
        "name": "Event Landing",
        "type_id": 1,
        "category": "Website",
        "description": "Create a tech conference landing page that pulses with energy. Bold hero with animated event date countdown and geometric background patterns, speaker grid where photos transform on hover with bio reveal, schedule timeline with horizontal scroll and session filtering, sponsor logos in an infinite marquee, and registration form with ticket tier comparison. Vibrant gradient theme (fuchsia to violet) with dark sections. Inspired by Web Summit and AWS re:Invent.",
        "featured": False,
    },
    {
        "name": "Podcast Website",
        "type_id": 1,
        "category": "Website",
        "description": "Build a podcast website that feels like a premium audio studio. Featured episode hero with animated waveform visualization and play button that pulses, episode list with hover-play previews and duration badges, host bios with warm portrait cards, subscribe buttons for all platforms with branded colors, and a contact form styled as a 'send us a voice message' CTA. Warm amber and charcoal palette with audio-reactive visual elements.",
        "featured": False,
    },
    {
        "name": "Non-Profit Website",
        "type_id": 1,
        "category": "Website",
        "description": "Create a non-profit website that inspires action through immersive storytelling. Full-screen hero with video background showing impact, animated statistics counters that count up on scroll, programs section with image cards that expand on hover revealing stories, donation form with progress bar that fills with warm gradient, volunteer signup with map of active locations, and a stories carousel with emotional photography. Warm, hopeful palette with earth greens and sky blues.",
        "featured": False,
    },
    # ── Telegram Bot Templates (2) ──
    # Bot tokens are read from env vars: TELEGRAM_BOT_TOKEN_1, _2
    # and DISCORD_BOT_TOKEN_1, _2. Set them before running the seed.
    {
        "name": "AI Assistant Bot",
        "type_id": 2,
        "category": "Telegram Bot",
        "bot_token_env": "TELEGRAM_BOT_TOKEN_1",
        "description": "Build 'Aria,' an intelligent Telegram AI assistant that feels like chatting with a brilliant, warm concierge. The bot greets users with a personalized welcome and an elegant inline keyboard menu — Ask AI, Weather, Translate, Summary, Settings. The /ask command streams thoughtful, well-formatted responses with typing indicators that build anticipation. Weather delivers beautifully formatted 5-day forecasts with emoji icons. Translate handles 20+ languages with instant detection. Conversation memory remembers context across messages, so follow-up questions feel natural. Rate limiting is invisible to good users but stops abuse cold. Admin commands allow broadcasting announcements. Every response uses clean inline keyboards, tasteful emoji accents, and graceful error messages that never expose raw exceptions. Inspired by ChatGPT's polish and Telegram's native design language.",
        "featured": True,
    },
    {
        "name": "Community Manager Bot",
        "type_id": 2,
        "category": "Telegram Bot",
        "bot_token_env": "TELEGRAM_BOT_TOKEN_2",
        "description": "Create 'Guardian,' a Telegram community management bot that makes group moderation feel effortless and professional. New members are welcomed with a warm message and an inline captcha button — verification completes in one tap. The /rules command displays guidelines in a beautifully formatted message with emoji section headers. Admin commands (/warn, /mute, /kick, /ban) include reason tracking and DM notifications to the affected user. Anti-spam detection runs silently with configurable thresholds — first offense warns, repeat offenses escalate automatically. A reputation system rewards helpful members with /rep points and a monthly leaderboard. Scheduled announcements post automatically at configured times. Every action is logged to a private admin channel with clean, color-coded embed-style messages. The tone is authoritative but friendly, never robotic.",
        "featured": False,
    },
    # ── Discord Bot Templates (2) ──
    {
        "name": "Moderation Discord Bot",
        "type_id": 3,
        "category": "Discord Bot",
        "bot_token_env": "DISCORD_BOT_TOKEN_1",
        "description": "Build 'Sentinel,' a Discord moderation bot that makes server management feel commanding and precise. Slash commands (/ban, /kick, /mute, /warn) are clean and fast, each producing a rich embed with the user's avatar, the moderator's name, the reason, and a color-coded severity indicator (yellow = warn, orange = mute, red = kick, dark red = ban). Auto-mod runs silently in the background with configurable filters for spam detection, link blocking, mention limits, and profanity — each rule logs to a private mod-log channel with the flagged message and action taken. The warning system escalates automatically: 3 warnings → 1h mute, 5 warnings → 24h mute, 7 warnings → kick. Reaction roles let members self-assign roles by tapping emoji on a welcome message. New members get a warm welcome embed with server rules and role selection. /userinfo shows a member's full history: join date, warnings, reputation, and activity stats. Every embed uses consistent branding — the bot's avatar as thumbnail, a dark theme with accent colors, and a professional footer.",
        "featured": True,
    },
    {
        "name": "Music Discord Bot",
        "type_id": 3,
        "category": "Discord Bot",
        "bot_token_env": "DISCORD_BOT_TOKEN_2",
        "description": "Create 'Harmony,' a Discord music bot that turns voice channels into a premium listening experience. The /play command searches YouTube and Spotify with smart autocomplete, queueing tracks instantly with a confirmation embed showing album art, title, duration, and requester. The now-playing embed is a living dashboard — a progress bar that updates in real-time, album thumbnail, and inline buttons for skip, pause, shuffle, and loop. Audio quality is pristine with optional filters: bass boost for EDM, nightcore for energy, vaporwave for chill. Queue management is visual — /queue shows the upcoming tracks as a formatted list with durations and requesters. Playlists can be saved with /playlist save and loaded later. DJ-only mode restricts control to users with the DJ role, preventing queue hijacking. The bot auto-disconnects after 5 minutes of idle to free resources. Every embed has consistent styling — dark background, accent gradient, album art thumbnails, and timestamps. Inspired by Rythm's reliability and Spotify's visual polish.",
        "featured": False,
    },
    # ── Scheduler Templates (2) ──
    {
        "name": "Price Alert Scheduler",
        "type_id": 5,
        "category": "Scheduler",
        "description": "Create 'MarketPulse,' a scheduled price alert system that delivers crypto and metals intelligence like a premium trading desk briefing. Track BTC, ETH, silver (XAG), and gold (XAU) prices via free public APIs (CoinGecko for crypto, gold-api.com for metals). Configurable alert rules fire when prices cross thresholds: 'Alert me when BTC drops below $60K' or 'Notify when silver rises 5% in 24h.' Each alert delivers to email AND Telegram with a beautifully formatted message: current price, 24h change percentage with green/red arrow indicators, a 7-day trend summary, and the alert condition that triggered. A daily market digest compiles all tracked assets into a single morning briefing with a clean table format. Multiple alert profiles let users track different thresholds for different assets. Scheduling is flexible — real-time alerts fire instantly when thresholds are crossed, digest summaries run daily:08:00. Messages use monospace numbers, emoji trend indicators (📈📉), and section headers for scannability. Inspired by TradingView alerts and Bloomberg morning briefings.",
        "featured": True,
    },
    {
        "name": "Daily Digest Scheduler",
        "type_id": 5,
        "category": "Scheduler",
        "description": "Build 'Morning Brief,' a daily digest scheduler that delivers a personalized intelligence briefing every morning at 7:00 AM. The digest compiles multiple data sources into one beautifully formatted email: a 5-day weather forecast with emoji icons and 'bring an umbrella' alerts, top 5 news headlines from configurable categories (tech, finance, sports) with AI-generated one-line summaries, a crypto portfolio snapshot showing top holdings with 24h change percentages and total portfolio value, upcoming calendar events for the day, and a curated motivational quote. Every Monday, a weekly summary replaces the daily digest with a 7-day retrospective: news trends, portfolio performance chart, weather patterns, and goal progress. The email uses clean HTML with section headers, monospace numbers for financial data, responsive mobile layout, and a warm professional tone. Users configure their preferences: which sections to include, delivery time, location for weather, and news categories. Inspired by Axios newsletters and Robinhood Snacks formatting.",
        "featured": False,
    },
]

# ──────────────────────────────────────────────────────────────────────
# Gallery definitions — premium descriptions following Prompt Builder standards
# ──────────────────────────────────────────────────────────────────────

GALLERY: List[Dict[str, Any]] = [
    {"name": "CRM Dashboard", "type_id": 1, "description": "Build a premium CRM dashboard that feels like a command center. Dark theme with neon-accented data tables, kanban deal pipeline with smooth drag-and-drop between stages, activity timeline with real-time pulse indicators, and sales metrics with animated charts. Glassmorphism cards, sidebar navigation with icons, and a search bar that filters across all data. Inspired by Linear and Attio."},
    {"name": "Restaurant Website", "type_id": 1, "description": "Create an immersive fine-dining restaurant website. Full-screen hero with cinematically blurred dish photography and elegant serif typography, menu presented as premium cards with hover-reveal ingredients, reservation form with date picker and time slot grid, photo gallery with lightbox, and location map with custom styling. Warm candlelit palette with gold accents."},
    {"name": "Gym Fitness", "type_id": 1, "description": "Build a high-energy gym website that motivates instantly. Bold hero with athletic photography and motivational text overlay, class schedule with filterable week view, trainer cards with specialty badges, membership pricing with comparison table, and a BMI calculator widget with animated results. Dark theme with electric green and orange neon accents, sharp angles, and dynamic imagery."},
    {"name": "Analytics Dashboard", "type_id": 1, "description": "Create a web analytics dashboard that turns data into visual art. Real-time traffic sources as animated flow diagram, visitor map with pulsing location dots, conversion funnel with step-through visualization, top pages with sparkline charts, and live active users counter. Clean, data-dense but breathable. Inspired by Plausible and Vercel Analytics."},
    {"name": "AI Chat Interface", "type_id": 1, "description": "Build a sleek AI chat interface that feels like talking to the future. Conversation history sidebar with search, streaming message display with typing animation, model selector dropdown, code blocks with syntax highlighting and copy button, and a settings panel for temperature/max tokens. Dark theme with subtle glow effects on active elements. Inspired by ChatGPT and Claude's clean UI."},
    {"name": "Booking System", "type_id": 1, "description": "Create an appointment booking system that makes scheduling feel effortless. Calendar view with available time slots highlighted, service menu with duration and pricing cards, booking confirmation with calendar add-to feature, reminder settings with notification preferences, and a dashboard for managing upcoming appointments. Clean, trustworthy design with clear CTAs and smooth transitions."},
    {"name": "Invoice System", "type_id": 1, "description": "Build a professional invoicing system that makes billing feel premium. Invoice list with status badges and quick filters, create-invoice form with dynamic line items and auto-tax calculation, PDF preview with print-ready formatting, payment status tracking with timeline, and client management with contact cards. Professional design with clean tables, branded invoice templates, and subtle animations."},
    {"name": "Crypto Dashboard", "type_id": 1, "description": "Create a real-time crypto tracking dashboard that feels like a trading terminal. Live price tickers with flash-on-update animation, portfolio allocation as interactive pie chart, recent transactions table with gas tracker, price alert setup with notification preferences, and candlestick charts with drawing tools. Dark theme with green/red indicators, monospace numbers, and data density inspired by TradingView."},
    {"name": "Agency Website", "type_id": 1, "description": "Build a creative agency website that showcases bold imagination. Portfolio grid with case study cards that expand on hover revealing project metrics, services section with icon animations and capability descriptions, team bios with personality-reveal hover states, client logos in an elegant infinite scroll, and a contact form with project type selector and budget range slider. Bold, modern design with smooth scroll animations."},
    {"name": "Real Estate Listings", "type_id": 1, "description": "Create a real estate site that makes property browsing feel aspirational. Search filters with map integration showing property pins, property cards with hero image carousels and key specs, detail page with full-gallery lightbox and mortgage calculator, agent contact form with availability matching, and saved favorites with comparison view. Clean, aspirational design with large imagery and premium typography."},
    # ── Bot + Scheduler gallery entries (2 per type) ──
    {"name": "Telegram Tip Bot", "type_id": 2, "bot_token_env": "TELEGRAM_BOT_TOKEN_3", "description": "Build 'Tippy,' a Telegram tip bot that makes community microtransactions feel generous and fun. The /tip @user 100 command sends a beautifully formatted receipt card with the recipient's name, amount in monospace, and a personalized message field. /balance shows a premium wallet card with current balance, lifetime sent/received totals, and a mini sparkline of recent activity. /withdraw generates a QR code inline for easy deposits. A daily bonus claim button appears every 24 hours with a satisfying 'Claimed!' animation. The leaderboard ranks top tippers weekly with medal emojis (🥇🥈🥉) and total tipped amounts. Transaction history is viewable as paginated inline cards with timestamps and counterparties. Admin treasury commands are hidden behind a clean dashboard menu. Inspired by NanoTipper's simplicity and Cash App's receipt design."},
    {"name": "Discord Giveaway Bot", "type_id": 3, "bot_token_env": "DISCORD_BOT_TOKEN_3", "description": "Create 'LuckyDraw,' a Discord giveaway bot that turns every contest into a community celebration. The /giveaway command launches a stunning embed — prize title with a trophy emoji, shimmering countdown timer that ticks down in real-time, participant counter that pulses with each new entry, and a prominent reaction button (🎉) that members tap to enter. When the timer hits zero, the winner reveal is dramatic: the embed transforms with a golden border, the winner's avatar and username display center-stage, confetti reactions flood the message, and the winner gets an instant DM with a claim button. /raffle draws instant winners for quick contests. Giveaway history tracks past winners, prize values, and participation rates. Role-restricted entries let admins limit giveaways to specific roles. Every embed uses the bot's branded color scheme — deep purple with gold accents for the premium contest feel. Inspired by GiveawayBot's reliability with premium visual polish."},
    {"name": "Weather Alert Scheduler", "type_id": 5, "description": "Build 'SkyWatch,' a scheduled weather alert system that delivers forecasts like a personal meteorologist. Every morning at 6:00 AM, a beautifully formatted weather briefing arrives via email and Telegram: current conditions with a large emoji icon (☀️⛅🌧️⛈️), hourly temperature graph for the next 12 hours, 'bring an umbrella' alerts when precipitation probability exceeds 40%, and a 7-day outlook as a scannable table. Severe weather alerts (storm warnings, heat advisories, frost alerts) fire immediately with a red-priority push notification including safety recommendations. Air quality index tracking shows AQI value with color-coded health categories (good/moderate/unhealthy). UV index warnings remind users to apply sunscreen when the index exceeds 6. Users configure multiple locations — home, work, travel destination — and switch between them. The message format uses clean section headers, emoji weather icons, and temperature trend arrows. Inspired by Carrot Weather's personality and Apple Weather's visual design."},
    {"name": "RSS Monitor Scheduler", "type_id": 5, "description": "Create 'FeedCurator,' an RSS feed monitor scheduler that delivers a curated content briefing like a personal editorial assistant. Users subscribe to multiple RSS feeds — TechCrunch, Hacker News, The Verge, specialized blogs — and the scheduler compiles new articles every 4 hours into a single digest email. Keyword filters work bidirectionally: 'include' keywords surface relevant articles ('AI, GPT, startup'), while 'exclude' keywords suppress noise ('crypto spam, sponsored, ad). Duplicate detection prevents the same story from appearing multiple times across feeds. Each article in the digest includes: source name as a badge, title as a link, a 2-line AI-generated summary that captures the key insight, and a relevance score. Trending topics across all feeds are highlighted at the top: '🔥 Trending: GPT-5, Apple Vision Pro, Startup Funding.' The digest uses a clean newsletter format with section dividers, monospace timestamps, and a table of contents at the top. Per-feed enable/disable lets users temporarily mute noisy sources. Inspired by Axios newsletters and Feedly's curation features."},
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


def _check_existing_projects() -> set[str]:
    """Fetch ALL existing project names to prevent duplicates.

    Queries the /projects endpoint (not /templates or /gallery) so we catch
    duplicates during the creation window — after create_project() returns
    but before mark_as_template() or publish_to_gallery() runs (~7 min gap).

    This is the PRIMARY dedup check. Called per-item inside the loop (not
    cached at startup) to catch duplicates created by concurrent runs.
    """
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    resp = _request("GET", f"{API_URL}/projects", headers=headers, timeout=15)
    if resp is None or resp.status_code not in (200, 201):
        log.warning("  ⚠️ Could not fetch existing projects — duplicate check disabled")
        return set()
    try:
        data = resp.json()
        # API returns a list of project dicts
        projects = data if isinstance(data, list) else data.get("projects", []) if isinstance(data, dict) else []
        names = set()
        for p in projects:
            if isinstance(p, dict):
                names.add(p.get("name", ""))
        return names
    except (json.JSONDecodeError, KeyError, TypeError):
        return set()


# ──────────────────────────────────────────────────────────────────────
# Core API operations
# ──────────────────────────────────────────────────────────────────────


def _headers() -> dict:
    return {"Authorization": f"Bearer {AUTH_TOKEN}", "Content-Type": "application/json"}


def create_project(name: str, description: str, type_id: int, bot_token: str = None, email_to: str = None) -> Optional[dict]:
    """Create a project via the API. Returns project dict or None.

    Handles 409 (another creation in progress) by waiting and retrying up to
    PROJECT_TIMEOUT seconds — the API enforces one creation at a time per user.

    Args:
        name: Project name
        description: Project description (build prompt)
        type_id: Project type (1=website, 2=telegram, 3=discord, 5=scheduler)
        bot_token: Bot token (required for type_id 2 and 3)
        email_to: Email recipient (for scheduler projects — SMTP auto-injected)
    """
    body: dict = {"name": name, "description": description, "type_id": type_id}
    if bot_token:
        body["bot_token"] = bot_token
    if email_to:
        body["email_to"] = email_to

    start = time.time()
    while time.time() - start < PROJECT_TIMEOUT:
        resp = _request(
            "POST",
            f"{API_URL}/projects",
            headers=_headers(),
            json_body=body,
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


def mark_as_template(project_id: int, title: str, description: str, category: str, featured: bool) -> bool:
    """Mark a completed project as a template.

    Passes the FULL description (not a generic 'Template: {title}' placeholder)
    so template cards in the /templates browser show the premium prompt text.
    """
    resp = _request(
        "POST",
        f"{API_URL}/projects/{project_id}/mark-as-template",
        headers=_headers(),
        json_body={
            "title": title,
            "description": description,
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
    type_filter: Optional[int] = None,
) -> RunStats:
    """Create all template projects with resume + duplicate protection."""
    stats = RunStats("Templates")
    stats.start_time = time.time()

    items = TEMPLATES
    if type_filter:
        items = [t for t in items if t.get("type_id") == type_filter]
    if limit:
        items = items[:limit]

    # Don't cache dedup check at startup — re-query per item to catch
    # duplicates created by concurrent runs or previous partial runs.
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

        # Resume check (progress file)
        if _is_completed(progress, "templates", name):
            log.info(f"  ⏭️ Skipped (already in progress file)")
            stats.skipped += 1
            continue

        # Per-item duplicate check — query projects table (not templates)
        # so we catch duplicates during the creation window.
        existing_projects = _check_existing_projects()
        if name in existing_projects:
            log.info(f"  ⏭️ Skipped (project already exists on server)")
            _mark_completed(progress, "templates", name, None, "already exists")
            stats.already_exists += 1
            continue

        # Resolve bot token from env if the template requires one
        bot_token = None
        token_env = tmpl.get("bot_token_env")
        if token_env:
            bot_token = os.getenv(token_env, "")
            if not bot_token:
                log.warning(f"  ⏭️ Skipped — {token_env} not set (required for bot project)")
                log.warning(f"      Set it: export {token_env}=<token_from_botfather_or_discord_portal>")
                stats.skipped += 1
                continue
            log.info(f"  Using bot token from {token_env}")

        # Create + wait + mark
        # For scheduler projects, pass email_to so they have a delivery channel
        email_to = os.getenv("SEED_EMAIL_TO", "") if tmpl.get("type_id") == 5 else None
        project = create_project(name, tmpl["description"], tmpl["type_id"], bot_token=bot_token, email_to=email_to)
        if not project:
            stats.failed += 1
            continue

        pid = project.get("id")
        log.info(f"  Created project {pid}, waiting for completion...")
        log.debug(f"  Project response: {json.dumps(project)[:200]}")

        # Write progress IMMEDIATELY after project creation — before
        # waiting for completion. If the process crashes during the
        # 7-minute build, the progress entry exists and the next run
        # won't recreate the project.
        _mark_completed(progress, "templates", name, pid, "project created, waiting for build")

        status = wait_for_completion(pid)
        if status == "completed":
            ok = mark_as_template(pid, name, tmpl["description"], tmpl["category"], tmpl.get("featured", False))
            if ok:
                log.info(f"  📋 Marked as template")
                # Update progress detail
                _mark_completed(progress, "templates", name, pid, "template published")
                stats.created += 1
            else:
                log.error(f"  ⚠️ Failed to mark as template (project still created)")
                stats.created += 1  # project exists, just template marking failed
        elif status == "timeout":
            log.warning(f"  ⏰ Build timed out — project {pid} exists but may be incomplete")
            stats.timeout += 1
        else:
            log.error(f"  ❌ Build failed")
            stats.failed += 1

    stats.end_time = time.time()
    return stats


def run_gallery(
    progress: Dict[str, Any],
    limit: Optional[int] = None,
    dry_run: bool = False,
    type_filter: Optional[int] = None,
) -> RunStats:
    """Create all gallery projects with resume + duplicate protection."""
    stats = RunStats("Gallery")
    stats.start_time = time.time()

    items = GALLERY
    if type_filter:
        items = [g for g in items if g.get("type_id") == type_filter]
    if limit:
        items = items[:limit]

    # Don't cache dedup check at startup — re-query per item
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

        # Resume check (progress file)
        if _is_completed(progress, "gallery", name):
            log.info(f"  ⏭️ Skipped (already in progress file)")
            stats.skipped += 1
            continue

        # Per-item duplicate check — query projects table
        existing_projects = _check_existing_projects()
        if name in existing_projects:
            log.info(f"  ⏭️ Skipped (project already exists on server)")
            _mark_completed(progress, "gallery", name, None, "already exists")
            stats.already_exists += 1
            continue

        # Resolve bot token from env if the gallery item requires one
        bot_token = None
        token_env = item.get("bot_token_env")
        if token_env:
            bot_token = os.getenv(token_env, "")
            if not bot_token:
                log.warning(f"  ⏭️ Skipped — {token_env} not set (required for bot project)")
                stats.skipped += 1
                continue

        # Create + wait + publish
        # For scheduler gallery projects, pass email_to
        gallery_email = os.getenv("SEED_EMAIL_TO", "") if item.get("type_id") == 5 else None
        project = create_project(name, item["description"], item["type_id"], bot_token=bot_token, email_to=gallery_email)
        if not project:
            stats.failed += 1
            continue

        pid = project.get("id")
        log.info(f"  Created project {pid}, waiting for completion...")
        log.debug(f"  Project response: {json.dumps(project)[:200]}")

        # Write progress IMMEDIATELY after project creation
        _mark_completed(progress, "gallery", name, pid, "project created, waiting for build")

        status = wait_for_completion(pid)
        if status == "completed":
            ok = publish_to_gallery(pid, name, item["description"], i <= 5)
            if ok:
                log.info(f"  🖼️ Published to gallery")
                _mark_completed(progress, "gallery", name, pid, "gallery published")
                stats.created += 1
            else:
                log.error(f"  ⚠️ Failed to publish to gallery (project still created)")
                stats.created += 1
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
    parser.add_argument("--type", type=int, default=None, help="Filter by project type_id (1=website, 2=telegram, 3=discord, 5=scheduler)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without calling API")
    parser.add_argument("--fresh", action="store_true", help="Ignore previous progress (no resume)")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from progress (default)")
    parser.add_argument("--parallel", type=int, default=1, help="Number of parallel workers (requires admin role)")
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
    if args.fresh and not args.dry_run:
        progress: Dict[str, Any] = {"templates": {}, "gallery": {}}
        _save_progress(progress)
        log.info("📂 Started fresh (progress file reset)")
    elif args.fresh and args.dry_run:
        progress: Dict[str, Any] = {"templates": {}, "gallery": {}}
        log.info("📂 Fresh mode (dry-run — progress file NOT reset)")
    else:
        progress = _load_progress()
        completed_t = len(progress.get("templates", {}))
        completed_g = len(progress.get("gallery", {}))
        if completed_t or completed_g:
            log.info(f"📂 Resuming: {completed_t} templates + {completed_g} gallery already done")

    # Run
    all_stats: List[RunStats] = []

    if args.parallel > 1:
        # Parallel mode: interleave templates + gallery, process with N threads.
        # Requires admin role on the API (bypasses one-creation-at-a-time guard).
        import threading

        all_items = []
        if args.all or args.templates:
            for t in TEMPLATES[:args.limit]:
                all_items.append(("template", t))
        if args.all or args.gallery:
            for g in GALLERY[:args.limit]:
                all_items.append(("gallery", g))

        # Interleave: template, gallery, template, gallery...
        interleaved = []
        t_items = [i for i in all_items if i[0] == "template"]
        g_items = [i for i in all_items if i[0] == "gallery"]
        max_len = max(len(t_items), len(g_items))
        for idx in range(max_len):
            if idx < len(t_items):
                interleaved.append(t_items[idx])
            if idx < len(g_items):
                interleaved.append(g_items[idx])

        # Filter out completed
        pending = [
            (kind, item) for kind, item in interleaved
            if not _is_completed(progress, kind + "s", item["name"])
        ]

        log.info(f"\n{'=' * 60}")
        log.info(f"PARALLEL MODE ({args.parallel} workers, {len(pending)} pending)")
        log.info(f"⚠️  Requires admin role on API (bypasses 1-at-a-time guard)")
        log.info(f"{'=' * 60}")

        if args.dry_run:
            for kind, item in pending:
                log.info(f"  [{kind}] {item['name']}")
            sys.exit(0)

        t_stats = RunStats("Templates")
        g_stats = RunStats("Gallery")
        t_stats.start_time = g_stats.start_time = time.time()
        lock = threading.Lock()
        item_idx = [0]  # mutable counter for thread-safe queue position

        def worker(worker_id: int) -> None:
            while True:
                with lock:
                    if item_idx[0] >= len(pending):
                        break
                    idx = item_idx[0]
                    item_idx[0] += 1
                    kind, item = pending[idx]

                name = item["name"]
                log.info(f"\n[W{worker_id}] [{idx+1}/{len(pending)}] {name}")

                # Duplicate check
                if kind == "template":
                    existing = _check_existing_templates()
                else:
                    existing = _check_existing_gallery()
                if name in existing:
                    log.info(f"  [W{worker_id}] ⏭️ Skipped (already exists on server)")
                    with lock:
                        _mark_completed(progress, kind + "s", name, None, "already exists")
                        if kind == "template":
                            t_stats.already_exists += 1
                        else:
                            g_stats.already_exists += 1
                    continue

                bot_token = None
                token_env = item.get("bot_token_env")
                if token_env:
                    bot_token = os.getenv(token_env, "")
                    if not bot_token:
                        log.warning(f"  [W{worker_id}] ⏭️ Skipped — {token_env} not set")
                        with lock:
                            if kind == "template":
                                t_stats.skipped += 1
                            else:
                                g_stats.skipped += 1
                        continue

                # For scheduler gallery projects, pass email_to
                gallery_email = os.getenv("SEED_EMAIL_TO", "") if item.get("type_id") == 5 else None
                project = create_project(name, item["description"], item["type_id"], bot_token=bot_token, email_to=gallery_email)
                if not project:
                    with lock:
                        if kind == "template":
                            t_stats.failed += 1
                        else:
                            g_stats.failed += 1
                    continue

                pid = project.get("id")
                log.info(f"  [W{worker_id}] Created project {pid}, waiting...")
                status = wait_for_completion(pid)

                if status == "completed":
                    if kind == "template":
                        ok = mark_as_template(pid, name, item["description"], item.get("category", "Website"), item.get("featured", False))
                    else:
                        ok = publish_to_gallery(pid, name, item["description"], False)
                    if ok:
                        log.info(f"  [W{worker_id}] ✅ Done: {name}")
                        with lock:
                            _mark_completed(progress, kind + "s", name, pid, "published")
                            if kind == "template":
                                t_stats.created += 1
                            else:
                                g_stats.created += 1
                    else:
                        log.error(f"  [W{worker_id}] ⚠️ Publish failed: {name}")
                        with lock:
                            if kind == "template":
                                t_stats.failed += 1
                            else:
                                g_stats.failed += 1
                elif status == "timeout":
                    with lock:
                        if kind == "template":
                            t_stats.timeout += 1
                        else:
                            g_stats.timeout += 1
                else:
                    with lock:
                        if kind == "template":
                            t_stats.failed += 1
                        else:
                            g_stats.failed += 1

        threads = [threading.Thread(target=worker, args=(i + 1,)) for i in range(args.parallel)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        t_stats.end_time = g_stats.end_time = time.time()
        all_stats.extend([t_stats, g_stats])

    elif args.all or args.templates:
        all_stats.append(run_templates(progress, args.limit, args.dry_run, type_filter=args.type))
    if (args.parallel <= 1 and args.all) or args.gallery:
        all_stats.append(run_gallery(progress, args.limit, args.dry_run, type_filter=args.type))

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
