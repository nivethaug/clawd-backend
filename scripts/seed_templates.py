#!/usr/bin/env python3
"""
Seed Templates + Gallery for v1.0 Release.

Creates real projects using the DreamAgent API, waits for completion,
then marks them as templates and publishes to gallery.

Usage:
    # Set these env vars first:
    export API_URL=https://api.dreamagent.cloud
    export AUTH_TOKEN=<your_bearer_token>
    export ADMIN_USER_ID=<your_user_id>

    python scripts/seed_templates.py --templates    # create templates only
    python scripts/seed_templates.py --gallery      # create gallery only
    python scripts/seed_templates.py --all           # create both

Each project takes ~5 minutes to generate. 15 templates + 20 gallery = ~35 projects.
Run in batches if needed.
"""

import argparse
import json
import os
import sys
import time

import requests

API_URL = os.getenv("API_URL", "https://api.dreamagent.cloud")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "1"))

if not AUTH_TOKEN:
    print("ERROR: Set AUTH_TOKEN env var (your Bearer token)")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {AUTH_TOKEN}",
    "Content-Type": "application/json",
}

# ──────────────────────────────────────────────────────────────────────
# TEMPLATE DEFINITIONS
# Each is a prompt that produces a high-quality, distinct result.
# ──────────────────────────────────────────────────────────────────────

TEMPLATES = [
    # ── Website (6) ──────────────────────────────────────────────
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
    # ── Telegram (4) ─────────────────────────────────────────────
    {
        "name": "AI Assistant Bot",
        "type_id": 2,
        "category": "Telegram",
        "description": "A Telegram bot that acts as an AI assistant. It responds to user questions with helpful answers, can set reminders, and provides daily quotes. Include /start, /help, /ask, and /reminder commands.",
        "featured": True,
    },
    {
        "name": "Community Bot",
        "type_id": 2,
        "category": "Telegram",
        "description": "A Telegram community management bot with welcome messages for new members, moderation commands (/ban, /mute, /warn), poll creation, and rules display. Include /start, /rules, /poll commands.",
        "featured": False,
    },
    {
        "name": "Alert Bot",
        "type_id": 2,
        "category": "Telegram",
        "description": "A Telegram bot that sends alerts and notifications. Monitor a URL for changes, send price alerts for cryptocurrencies, and schedule recurring reminders. Include /alert, /price, /subscribe commands.",
        "featured": False,
    },
    {
        "name": "Support Bot",
        "type_id": 2,
        "category": "Telegram",
        "description": "A Telegram customer support bot with a ticket system, FAQ responses, and escalation to human agents. Include /ticket, /faq, /status commands with inline keyboard buttons.",
        "featured": False,
    },
    # ── Discord (5) ──────────────────────────────────────────────
    {
        "name": "Moderation Bot",
        "type_id": 3,
        "category": "Discord",
        "description": "A Discord moderation bot with slash commands for ban, kick, mute, warn, and purge. Include logging channel, auto-role on join, and a case tracking system. Slash commands: /ban, /kick, /warn, /purge.",
        "featured": True,
    },
    {
        "name": "Ticket System",
        "type_id": 3,
        "category": "Discord",
        "description": "A Discord ticket bot that allows users to create support tickets via a button panel. Tickets create private channels, assign staff, and close with a transcript. Include /ticket panel setup and /close command.",
        "featured": True,
    },
    {
        "name": "AI Knowledge Base",
        "type_id": 3,
        "category": "Discord",
        "description": "A Discord bot that answers questions from a knowledge base using AI. It searches documentation, provides code examples, and learns from user feedback. Slash command: /ask with autocomplete.",
        "featured": False,
    },
    {
        "name": "Community Engagement",
        "type_id": 3,
        "category": "Discord",
        "description": "A Discord community bot with leveling system, XP tracking, reaction roles, and giveaway management. Include /rank, /leaderboard, /giveaway, /reaction-role commands.",
        "featured": False,
    },
    {
        "name": "Server Logger",
        "type_id": 3,
        "category": "Discord",
        "description": "A Discord logging bot that tracks member joins/leaves, message edits/deletes, role changes, and channel updates. Sends formatted embed logs to a designated channel. Slash command: /log-config.",
        "featured": False,
    },
    # ── Scheduler (5) ────────────────────────────────────────────
    {
        "name": "Daily Report",
        "type_id": 5,
        "category": "Scheduler",
        "description": "A scheduler that generates a daily summary report from multiple data sources (mock metrics), formats it as an HTML email, and sends it at 9 AM every day. Include metrics dashboard, trend arrows, and key highlights.",
        "featured": True,
    },
    {
        "name": "Email Scheduler",
        "type_id": 5,
        "category": "Scheduler",
        "description": "A scheduler that sends automated email sequences. Users define a sequence of emails with delays (e.g., welcome email, day 3 tutorial, day 7 tips). Track open rates and send-time optimization.",
        "featured": False,
    },
    {
        "name": "Price Monitor",
        "type_id": 5,
        "category": "Scheduler",
        "description": "A scheduler that monitors cryptocurrency prices every 5 minutes, sends an alert when a price crosses a threshold, and maintains a price history chart. Include configurable alerts and a dashboard.",
        "featured": False,
    },
    {
        "name": "Webhook Automation",
        "type_id": 5,
        "category": "Scheduler",
        "description": "A scheduler that listens for webhooks, transforms the payload, and forwards to multiple destinations (Slack, email, Discord). Include retry logic, rate limiting, and a transformation editor.",
        "featured": False,
    },
    {
        "name": "Social Media Scheduler",
        "type_id": 5,
        "category": "Scheduler",
        "description": "A scheduler that queues social media posts across platforms, schedules them at optimal times, and tracks engagement. Include a content calendar view and post preview.",
        "featured": False,
    },
]

# ──────────────────────────────────────────────────────────────────────
# GALLERY DEFINITIONS (subset of templates + extras)
# Gallery items are polished examples that inspire users.
# ──────────────────────────────────────────────────────────────────────

GALLERY = [
    {"name": "CRM Dashboard", "type_id": 1, "description": "A modern CRM dashboard with contact management, deal pipeline (kanban), activity timeline, and sales metrics. Drag-and-drop deals between stages. Premium dark UI with data tables and charts."},
    {"name": "Restaurant Website", "type_id": 1, "description": "An elegant restaurant website with a full-screen hero image, menu cards with prices, reservation form, photo gallery, and location map. Warm, appetizing design with elegant typography."},
    {"name": "Gym Fitness", "type_id": 1, "description": "A high-energy gym website with bold hero section, class schedule table, trainer cards, membership pricing tiers, and a BMI calculator widget. Dark theme with neon accents, motivational imagery."},
    {"name": "School Portal", "type_id": 1, "description": "A school management portal with course catalog, student dashboard, grade tracking, assignment submission, and announcements feed. Clean, friendly design with a focus on usability."},
    {"name": "HR Dashboard", "type_id": 1, "description": "An HR management dashboard with employee directory, leave request tracking, performance review cycle, and org chart. Professional design with charts and data tables."},
    {"name": "Crypto Dashboard", "type_id": 1, "description": "A real-time crypto tracking dashboard with price tickers, portfolio allocation pie chart, recent transactions, and price alerts setup. Dark theme with green/red price indicators."},
    {"name": "Analytics Dashboard", "type_id": 1, "description": "A web analytics dashboard with traffic sources, visitor map, conversion funnel, top pages, and real-time active users. Data-dense but clean, inspired by Plausible Analytics."},
    {"name": "Agency Website", "type_id": 1, "description": "A creative agency website with portfolio grid, services with hover effects, team bios, client logos carousel, and a contact form with project type selector. Bold, modern design with smooth animations."},
    {"name": "AI Chat Interface", "type_id": 1, "description": "A sleek AI chat interface with conversation history sidebar, streaming message display, model selector, and code block syntax highlighting. Dark theme inspired by ChatGPT."},
    {"name": "Booking System", "type_id": 1, "description": "An appointment booking system with calendar view, time slot selection, service menu, booking confirmation, and reminder settings. Clean, trustworthy design with clear CTAs."},
    {"name": "Inventory Manager", "type_id": 1, "description": "An inventory management system with product table, stock level indicators, low-stock alerts, category filters, and barcode placeholder. Data-dense table with inline editing."},
    {"name": "Invoice System", "type_id": 1, "description": "An invoicing system with invoice list, create-invoice form with line items, PDF preview, payment status tracking, and client management. Professional, clean design with print-ready invoices."},
    {"name": "Helpdesk", "type_id": 1, "description": "A customer helpdesk with ticket inbox, priority queues, agent assignment, canned responses, and SLA timers. Split-panel design with ticket list + detail view."},
    {"name": "ERP System", "type_id": 1, "description": "A mini ERP dashboard with modules for sales, inventory, finance, and HR. Tabbed interface with summary cards, data tables, and export buttons. Professional enterprise design."},
    {"name": "Real Estate Listings", "type_id": 1, "description": "A real estate listing site with property search filters, map view, property cards with photos, detail page with gallery, and agent contact form. Clean, aspirational design."},
]


def create_project(name: str, description: str, type_id: int) -> dict:
    """Create a project via the API."""
    resp = requests.post(
        f"{API_URL}/projects",
        headers=HEADERS,
        json={"name": name, "description": description, "type_id": type_id},
        timeout=30,
    )
    if resp.status_code == 402:
        print(f"  ❌ BLOCKED: insufficient credits. Buy credits and retry.")
        return None
    if resp.status_code != 200:
        print(f"  ❌ Error {resp.status_code}: {resp.text[:200]}")
        return None
    return resp.json()


def wait_for_completion(project_id: int, timeout: int = 600) -> str:
    """Poll project status until ready/failed."""
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(
            f"{API_URL}/projects/{project_id}/status",
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            status = resp.json().get("status", "unknown")
            elapsed = int(time.time() - start)
            if status in ("ready", "running"):
                print(f"  ✅ Completed in {elapsed}s")
                return status
            if status in ("failed", "error"):
                print(f"  ❌ Failed after {elapsed}s")
                return status
            if elapsed % 60 == 0 and elapsed > 0:
                print(f"  ⏳ Still {status} after {elapsed}s...")
        time.sleep(10)
    print(f"  ⏰ Timeout after {timeout}s")
    return "timeout"


def mark_as_template(project_id: int, title: str, category: str, featured: bool) -> bool:
    """Mark a completed project as a template."""
    resp = requests.post(
        f"{API_URL}/projects/{project_id}/mark-as-template",
        headers=HEADERS,
        json={
            "title": title,
            "description": f"Template: {title}",
            "category": category,
            "is_featured": featured,
        },
        timeout=10,
    )
    return resp.status_code == 201


def publish_to_gallery(project_id: int, title: str, description: str, featured: bool) -> bool:
    """Publish a completed project to the gallery."""
    resp = requests.post(
        f"{API_URL}/projects/{project_id}/publish-to-gallery",
        headers=HEADERS,
        json={
            "title": title,
            "description": description,
            "is_featured": featured,
        },
        timeout=10,
    )
    return resp.status_code == 201


def run_templates():
    """Create all template projects."""
    print(f"\n{'='*60}")
    print(f"CREATE TEMPLATES ({len(TEMPLATES)} items)")
    print(f"{'='*60}\n")

    success = 0
    for i, tmpl in enumerate(TEMPLATES, 1):
        print(f"[{i}/{len(TEMPLATES)}] {tmpl['name']} ({tmpl['category']})")
        project = create_project(tmpl["name"], tmpl["description"], tmpl["type_id"])
        if not project:
            continue
        pid = project.get("id")
        print(f"  Created project {pid}, waiting for completion...")
        status = wait_for_completion(pid)
        if status in ("ready", "running"):
            ok = mark_as_template(pid, tmpl["name"], tmpl["category"], tmpl.get("featured", False))
            if ok:
                print(f"  📋 Marked as template")
                success += 1
            else:
                print(f"  ⚠️ Failed to mark as template")
        print()

    print(f"\nTemplates created: {success}/{len(TEMPLATES)}")


def run_gallery():
    """Create all gallery projects."""
    print(f"\n{'='*60}")
    print(f"CREATE GALLERY ({len(GALLERY)} items)")
    print(f"{'='*60}\n")

    success = 0
    for i, item in enumerate(GALLERY, 1):
        print(f"[{i}/{len(GALLERY)}] {item['name']}")
        project = create_project(item["name"], item["description"], item["type_id"])
        if not project:
            continue
        pid = project.get("id")
        print(f"  Created project {pid}, waiting for completion...")
        status = wait_for_completion(pid)
        if status in ("ready", "running"):
            ok = publish_to_gallery(pid, item["name"], item["description"], i <= 5)
            if ok:
                print(f"  🖼️ Published to gallery")
                success += 1
            else:
                print(f"  ⚠️ Failed to publish to gallery")
        print()

    print(f"\nGallery items created: {success}/{len(GALLERY)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed templates + gallery for v1.0")
    parser.add_argument("--templates", action="store_true", help="Create templates only")
    parser.add_argument("--gallery", action="store_true", help="Create gallery only")
    parser.add_argument("--all", action="store_true", help="Create both (default)")
    args = parser.parse_args()

    if not args.templates and not args.gallery and not args.all:
        args.all = True

    if args.all or args.templates:
        run_templates()
    if args.all or args.gallery:
        run_gallery()

    print(f"\n{'='*60}")
    print("SEED COMPLETE")
    print(f"{'='*60}")
