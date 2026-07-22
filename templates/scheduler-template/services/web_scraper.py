"""
Web Scraper — calls the server-side Chrome DevTools scraping API.

This module provides the SAME interface as the old CDP-based web_scraper
(ScrapeConfig, ScrapeResult, scrape_url, WebScraper) but delegates the
actual Chrome rendering to the platform's /internal/scrape endpoint.

HOW IT WORKS:
    Your code (bwrap sandbox / Docker container)
      → HTTP POST to BACKEND_URL/internal/scrape
        → Server-side Chrome renders the page
        → Your extraction JS runs in Chrome
        ← JSON data returned

The executor's sandbox does NOT have Chrome installed. Chrome runs once on
the main VPS as a systemd service. This module is a thin HTTP client that
calls the scraping API — no local browser needed.

USAGE:
    from services.web_scraper import scrape_url, ScrapeConfig

    # Simple extraction
    config = ScrapeConfig(
        url="https://example.com",
        fields={"title": "h1", "price": ".price"}
    )
    result = scrape_url(config)
    print(result.data)

    # Custom JS extraction (full power — any JS that returns a value)
    config = ScrapeConfig(
        url="https://example.com",
        js_extract="return Array.from(document.querySelectorAll('.item')).map(e => e.textContent.trim())"
    )
    result = scrape_url(config)
    print(result.data)

    # With pagination + wait
    config = ScrapeConfig(
        url="https://example.com/products",
        items_selector=".product",
        fields={"name": ".name", "price": ".price"},
        wait_for=["Loading complete"],
        max_pages=3,
        scroll=True
    )
    result = scrape_url(config)
"""

import os
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests


# ---------------------------------------------------------------------------
# Configuration data classes (unchanged interface for backward compat)
# ---------------------------------------------------------------------------

@dataclass
class ScrapeConfig:
    """Per-site selector configuration for scraping."""
    url: str
    items_selector: str = ""  # CSS selector for list of items
    fields: Dict[str, str] = field(default_factory=dict)  # field_name → CSS selector
    wait_for: Optional[List[str]] = None  # text/selector to wait for before extracting
    pagination: Optional[str] = None  # next-page button selector (not supported via API yet)
    max_pages: int = 1  # maximum pages to scrape
    scroll: bool = False  # scroll to bottom for lazy-loaded content
    auth: Optional[Dict[str, str]] = None  # login config (not supported via API yet)
    js_extract: Optional[str] = None  # raw JS string for complex extraction
    timeout: int = 15  # scrape timeout in seconds


@dataclass
class ScrapeResult:
    """Structured output from scraping operation."""
    url: str
    data: Any = None  # extracted data (list of dicts, or raw value)
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

# Resolve the scraping API URL. Uses BACKEND_URL (same as job_manager.py).
# During chat/creation: BACKEND_URL is set by env_injector to the public API.
# During sandbox execution: loaded from project .env via config.py.
SCRAPER_API_URL = os.getenv("BACKEND_URL", "https://api.dreamagent.cloud")
SCRAPER_TIMEOUT = 30  # HTTP request timeout (Chrome render can take time)


def _build_extract_js(config: ScrapeConfig) -> str:
    """Build the JavaScript extraction function from ScrapeConfig.

    If js_extract is provided, use it directly (full custom power).
    Otherwise, build from items_selector + fields.
    """
    if config.js_extract:
        return config.js_extract

    if not config.items_selector:
        # Simple page extraction — return page title + text
        return "return { title: document.title, text: document.body.innerText.substring(0, 5000) }"

    # Build item extraction JS from selector + fields
    fields_json = json.dumps(config.fields)
    return f"""
        const items = document.querySelectorAll('{config.items_selector}');
        const fieldMap = {fields_json};
        return Array.from(items).map(item => {{
            const obj = {{}};
            for (const [field, selector] of Object.entries(fieldMap)) {{
                const el = item.querySelector(selector);
                if (el) {{
                    if (el.tagName === 'A') {{
                        obj[field] = {{ text: el.textContent.trim(), href: el.href }};
                    }} else if (el.tagName === 'IMG') {{
                        obj[field] = {{ src: el.src, alt: el.alt || '' }};
                    }} else {{
                        obj[field] = el.textContent.trim();
                    }}
                }} else {{
                    obj[field] = null;
                }}
            }}
            return obj;
        }});
    """


def _build_wait_selector(config: ScrapeConfig) -> Optional[str]:
    """Extract a CSS selector to wait for from config.wait_for."""
    if not config.wait_for:
        return None
    # wait_for is a list of texts/selectors — use the first one that looks like a CSS selector
    for wf in config.wait_for:
        if any(c in wf for c in ".#["):
            return wf
    return None


def scrape_url(config: "ScrapeConfig") -> "ScrapeResult":
    """Scrape a URL using the server-side scraping API (tiered).

    Tries fast HTML mode first (render=False). If the page needs JS rendering
    (config.scroll, config.auth, or caller sets render=True), uses Chrome CDP.

    Args:
        config: ScrapeConfig with url, selectors, and options

    Returns:
        ScrapeResult with extracted data
    """
    start_time = time.time()
    result = ScrapeResult(url=config.url)

    try:
        extract_js = _build_extract_js(config)
        wait_selector = _build_wait_selector(config)
        wait_ms = 3000 if config.scroll else 2000

        # If scroll is requested, add scroll JS before extraction
        if config.scroll:
            extract_js = f"window.scrollTo(0, document.body.scrollHeight); " + extract_js

        # Decide render mode:
        # - render=True (Chrome CDP) if: scroll, auth, or pagination requested
        #   (these need a real browser to execute JS / interact)
        # - render=False (fast HTTP) for simple extraction (default)
        needs_render = config.scroll or config.auth or config.pagination

        endpoint = f"{SCRAPER_API_URL}/internal/scrape"
        payload = {
            "url": config.url,
            "extract_js": extract_js,
            "wait_for_selector": wait_selector,
            "wait_ms": wait_ms,
            "timeout": config.timeout,
            "render": needs_render,
        }

        resp = requests.post(endpoint, json=payload, timeout=SCRAPER_TIMEOUT)

        if resp.status_code != 200:
            result.errors.append(f"API returned HTTP {resp.status_code}: {resp.text[:200]}")
            return result

        data = resp.json()
        if data.get("success"):
            result.data = data.get("data")
            result.metadata["pages_scraped"] = 1
            result.metadata["total_items"] = len(result.data) if isinstance(result.data, list) else 1
        else:
            result.errors.append(data.get("error", "Unknown scrape error"))

    except requests.exceptions.Timeout:
        result.errors.append("Scrape API request timed out")
    except requests.exceptions.ConnectionError as e:
        result.errors.append(f"Cannot reach scrape API at {SCRAPER_API_URL}: {e}")
    except Exception as e:
        result.errors.append(str(e))

    result.duration_ms = (time.time() - start_time) * 1000
    return result


# ---------------------------------------------------------------------------
# Compatibility shims — keep old class-based interface working
# ---------------------------------------------------------------------------

class WebScraper:
    """Backward-compat wrapper. Delegates to scrape_url via the API."""

    def __init__(self, config: ScrapeConfig):
        self.config = config

    def scrape(self) -> ScrapeResult:
        """Run the scrape."""
        return scrape_url(self.config)

    def connect(self):
        """No-op — no local Chrome connection needed."""
        pass

    def close(self):
        """No-op."""
        pass

    # The following methods are kept for code that subclasses WebScraper.
    # They build a ScrapeConfig and call scrape_url under the hood.

    def navigate(self, url: str) -> bool:
        self.config.url = url
        return True

    def extract_text(self, selector: str) -> Optional[str]:
        result = scrape_url(ScrapeConfig(
            url=self.config.url,
            js_extract=f"const el = document.querySelector('{selector}'); return el ? el.textContent.trim() : null",
            timeout=self.config.timeout,
        ))
        return result.data if not result.errors else None

    def extract_list(self, selector: str) -> List[str]:
        result = scrape_url(ScrapeConfig(
            url=self.config.url,
            js_extract=f"return Array.from(document.querySelectorAll('{selector}')).map(e => e.textContent.trim())",
            timeout=self.config.timeout,
        ))
        return result.data if isinstance(result.data, list) and not result.errors else []

    def extract_table(self, selector: str) -> List[Dict[str, str]]:
        js = f"""
            const table = document.querySelector('{selector}');
            if (!table) return [];
            const rows = Array.from(table.querySelectorAll('tr'));
            if (rows.length === 0) return [];
            const headers = Array.from(rows[0].querySelectorAll('th, td'))
                .map(th => th.textContent.trim().toLowerCase().replace(/\\s+/g, '_'));
            return rows.slice(1).map(row => {{
                const cells = Array.from(row.querySelectorAll('td'));
                const rowObj = {{}};
                cells.forEach((cell, i) => {{
                    if (headers[i]) rowObj[headers[i]] = cell.textContent.trim();
                }});
                return rowObj;
            }});
        """
        result = scrape_url(ScrapeConfig(url=self.config.url, js_extract=js, timeout=self.config.timeout))
        return result.data if isinstance(result.data, list) and not result.errors else []

    def extract_links(self, selector: str = "a") -> List[Dict[str, str]]:
        result = scrape_url(ScrapeConfig(
            url=self.config.url,
            js_extract=f"""return Array.from(document.querySelectorAll('{selector}')).map(link => ({{text: link.textContent.trim(), href: link.href, title: link.title || ''}}))""",
            timeout=self.config.timeout,
        ))
        return result.data if isinstance(result.data, list) and not result.errors else []

    def evaluate_script(self, js_body: str) -> Any:
        result = scrape_url(ScrapeConfig(
            url=self.config.url,
            js_extract=js_body,
            timeout=self.config.timeout,
        ))
        return result.data if not result.errors else {"error": result.errors[0]}


class NewsScraperExample(WebScraper):
    """Example news site scraper."""
    pass


class EcommerceScraperExample(WebScraper):
    """Example e-commerce product page scraper."""
    pass


# Scraper registry (for LLM extensibility — kept for backward compat)
_registry: Dict[str, type] = {}


def register_scraper(name: str, scraper_class: type):
    """Register a custom scraper class."""
    _registry[name] = scraper_class


def get_scraper(name: str) -> Optional[type]:
    """Get a registered scraper class."""
    return _registry.get(name)


def scrape_with_scraper(name: str, config: ScrapeConfig) -> ScrapeResult:
    """Scrape using a registered scraper."""
    scraper_class = _registry.get(name)
    if not scraper_class:
        return ScrapeResult(url=config.url, errors=[f"Unknown scraper: {name}"])
    scraper = scraper_class(config)
    return scraper.scrape()
