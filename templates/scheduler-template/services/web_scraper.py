"""
CDP Web Scraper Template for Bots

A Chrome DevTools Protocol (CDP) scraping template designed for LLMs to extend
for any website. Built on the MCPClient pattern.

USAGE:
    # Standalone usage
    from services.web_scraper import scrape_url, ScrapeConfig
    config = ScrapeConfig(url="https://example.com", items_selector=".item", fields={"title": ".title"})
    result = scrape_url(config)
    print(result.data)

    # Custom scraper
    from services.web_scraper import WebScraper, ScrapeConfig
    class MyScraper(WebScraper):
        def scrape(self):
            self.navigate(self.config.url)
            self.wait_for_text("loaded")
            return self.extract_by_config(self.config)

EXAMPLES:
    See NewsScraperExample and EcommerceScraperExample at bottom of file.
"""

import subprocess
import json
import time
import re
import os
import shutil
import urllib.request
from urllib.error import URLError
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime


# -----------------------------------------------------------------------------
#  Configuration Data Classes
# -----------------------------------------------------------------------------

@dataclass
class ScrapeConfig:
    """Per-site selector configuration for scraping."""
    url: str
    items_selector: str  # CSS selector for list of items
    fields: Dict[str, str]  # field_name → CSS selector (relative to item)
    wait_for: Optional[List[str]] = None  # text/selector to wait for before extracting
    pagination: Optional[str] = None  # next-page button selector
    max_pages: int = 1  # maximum pages to scrape
    scroll: bool = False  # scroll to bottom for lazy-loaded content
    auth: Optional[Dict[str, str]] = None  # login config (url, user_selector, pass_selector, submit_selector, username, password)
    js_extract: Optional[str] = None  # raw JS string for complex extraction
    timeout: int = 10000  # default timeout in ms


@dataclass
class ScrapeResult:
    """Structured output from scraping operation."""
    url: str
    data: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return asdict(self)


# -----------------------------------------------------------------------------
#  MCP Client (from reference implementation)
# -----------------------------------------------------------------------------

class MCPClient:
    """Direct MCP server communication from Python for Chrome DevTools Protocol."""

    def __init__(self):
        self.process = None
        self.chrome_process = None
        self.started_chrome = False
        self.request_id = 0
        self.tools: List[Dict] = []

    def _is_debug_port_ready(self) -> bool:
        """Check if Chrome debugging port is ready."""
        try:
            with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2):
                return True
        except (URLError, TimeoutError, OSError):
            return False

    def _find_chrome_executable(self) -> Optional[str]:
        """Find Chrome or Edge executable."""
        env_path = os.getenv("CHROME_PATH")
        if env_path and Path(env_path).exists():
            return env_path

        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]

        for exe in candidates:
            if Path(exe).exists():
                return exe

        return shutil.which("chrome") or shutil.which("msedge")

    def _ensure_chrome_debugging(self):
        """Ensure Chrome is running with debugging port 9222."""
        if self._is_debug_port_ready():
            print("[OK] Chrome debugging endpoint ready on :9222")
            return

        chrome_exe = self._find_chrome_executable()
        if not chrome_exe:
            raise RuntimeError(
                "Chrome/Edge not found. Install browser or set CHROME_PATH, then run with "
                "--remote-debugging-port=9222."
            )

        profile_dir = Path(r"C:\Temp\chrome-mcp-debug-profile")
        profile_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            chrome_exe,
            "--remote-debugging-port=9222",
            f"--user-data-dir={str(profile_dir)}",
            "--no-first-run",
        ]

        print(f"[NET] Launching browser for DevTools: {chrome_exe}")
        self.chrome_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.started_chrome = True

        for _ in range(20):
            if self._is_debug_port_ready():
                print("[OK] Chrome DevTools endpoint is live")
                return
            time.sleep(0.5)

        raise RuntimeError("Chrome launched but DevTools endpoint :9222 is not reachable")

    def _tool_text(self, result: Dict[str, Any]) -> str:
        """Extract text from tool result."""
        if isinstance(result, dict):
            return str(result.get("text", ""))
        return str(result)

    def _ensure_mcp_browser_connection(self):
        """Ensure MCP server is connected to browser."""
        for attempt in range(1, 6):
            probe = self.call_tool("list_pages", {})
            text = self._tool_text(probe)
            if "Could not connect to Chrome" not in text:
                print("[OK] MCP connected to browser target")
                return

            print(f"[WARN] MCP browser connection retry {attempt}/5")
            if attempt == 1:
                self._ensure_chrome_debugging()
            time.sleep(1)

        raise RuntimeError(
            "MCP could not connect to Chrome after retries. Ensure browser is running with "
            "--remote-debugging-port=9222."
        )

    def start_server(self):
        """Start MCP server and connect to Chrome."""
        self._ensure_chrome_debugging()
        print("[STARTING] MCP server...")
        cmd = (
            "npx --registry https://registry.npmjs.org "
            "chrome-devtools-mcp@0.20.2 --browserUrl=http://127.0.0.1:9222"
        )
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=True,
        )
        time.sleep(2)
        print("[OK] MCP server started")
        self._initialize()
        self._load_tools()
        self._ensure_mcp_browser_connection()

    def _send_request(self, method: str, params: Optional[Dict] = None) -> Dict:
        """Send JSON-RPC request to MCP server."""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {},
        }
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("No response from MCP server")
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")
        return response.get("result", {})

    def _initialize(self):
        """Initialize MCP connection."""
        print("[INIT] Initializing MCP connection...")
        result = self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "web-scraper", "version": "1.0.0"},
            },
        )
        print(f"[OK] Connected to: {result.get('serverInfo', {}).get('name', 'Unknown')}")
        self.process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        self.process.stdin.flush()

    def _load_tools(self):
        """Load available MCP tools."""
        print("[LOAD] Loading available tools...")
        result = self._send_request("tools/list")
        self.tools = result.get("tools", [])
        print(f"[OK] Found {len(self.tools)} tools")

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict:
        """Call an MCP tool with arguments."""
        result = self._send_request("tools/call", {"name": tool_name, "arguments": arguments})
        content = result.get("content", [])
        return content[0] if content else result

    def close(self):
        """Close MCP server and browser."""
        if self.process:
            self.process.terminate()
            self.process.wait()
            print("[OK] MCP server stopped")
        if self.started_chrome and self.chrome_process and self.chrome_process.poll() is None:
            self.chrome_process.terminate()
            print("[OK] Browser debug session stopped")


# -----------------------------------------------------------------------------
#  Web Scraper Base Class
# -----------------------------------------------------------------------------

class WebScraper:
    """Base class for web scrapers using Chrome DevTools Protocol."""

    MAX_RETRIES = 5
    BASE_DELAY = 0.2  # Base delay for exponential backoff in seconds

    def __init__(self, config: ScrapeConfig):
        self.config = config
        self.mcp = MCPClient()
        self.page_id = None

    def connect(self):
        """Connect to MCP server and browser."""
        self.mcp.start_server()
        # Open new page and get page ID
        result = self.mcp.call_tool("new_page", {"url": "about:blank"})
        self.page_id = result.get("pageId")

    def navigate(self, url: str) -> bool:
        """Navigate to URL with retry logic."""
        for attempt in range(self.MAX_RETRIES):
            try:
                self.mcp.call_tool("navigate_page", {"type": "url", "url": url})
                time.sleep(1)  # Wait for initial load
                return True
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise
                delay = self.BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
        return False

    def take_snapshot(self) -> str:
        """Take an accessibility-tree snapshot (token-efficient)."""
        result = self.mcp.call_tool("take_snapshot", {})
        return result.get("text", "")

    def evaluate_script(self, fn_body: str) -> Any:
        """Evaluate JavaScript with auto try/catch."""
        safe = f"""() => {{
            try {{
                {fn_body}
            }} catch(e) {{
                return {{ error: e.message }};
            }}
        }}"""
        result = self.mcp.call_tool("evaluate_script", {"function": safe})
        raw = result.get("text", "{}")

        try:
            if "```json" in raw:
                match = re.search(r'```json\s*(.*?)\s*```', raw, re.DOTALL)
                if match:
                    raw = match.group(1)
            elif "```" in raw:
                match = re.search(r'```\s*(.*?)\s*```', raw, re.DOTALL)
                if match:
                    raw = match.group(1)

            raw = raw.strip()
            if raw.startswith("{"):
                return json.loads(raw)
            return {"raw": raw}
        except Exception:
            return {"raw": raw}

    def find_uid(self, snapshot: str, pattern: str) -> Optional[str]:
        """Find element UID in snapshot using regex pattern."""
        m = re.search(pattern, snapshot, re.IGNORECASE)
        return m.group(1) if m else None

    def click_uid(self, uid: str):
        """Click element by UID."""
        self.mcp.call_tool("click", {"uid": uid})
        time.sleep(0.3)  # Allow UI to respond

    def fill_uid(self, uid: str, value: str):
        """Fill input element by UID."""
        self.mcp.call_tool("fill", {"uid": uid, "value": value})
        time.sleep(0.2)

    def type_text(self, text: str, submit_key: Optional[str] = None):
        """Type text into focused element."""
        kwargs = {"text": text}
        if submit_key:
            kwargs["submitKey"] = submit_key
        self.mcp.call_tool("type_text", kwargs)

    def press_key(self, key: str):
        """Press keyboard key/combination."""
        self.mcp.call_tool("press_key", {"key": key})

    def wait_for(self, texts: List[str], timeout: int = 8000):
        """Wait for text to appear on page."""
        try:
            self.mcp.call_tool("wait_for", {"text": texts, "timeout": timeout})
        except Exception:
            pass

    def wait_for_text(self, text: str, timeout: int = 8000):
        """Wait for specific text to appear."""
        self.wait_for([text], timeout)

    def scroll_to_bottom(self):
        """Scroll page to bottom for lazy-loaded content."""
        self.evaluate_script("""
            window.scrollTo(0, document.body.scrollHeight);
        """)
        time.sleep(0.5)

    def extract_text(self, selector: str) -> Optional[str]:
        """Extract text from element matching CSS selector."""
        result = self.evaluate_script(f"""
            const el = document.querySelector('{selector}');
            return el ? el.textContent.trim() : null;
        """)
        if isinstance(result, dict):
            return result.get("raw")
        return result

    def extract_list(self, selector: str) -> List[str]:
        """Extract text from all elements matching CSS selector."""
        result = self.evaluate_script(f"""
            const els = document.querySelectorAll('{selector}');
            return Array.from(els).map(el => el.textContent.trim());
        """)
        if isinstance(result, dict):
            return result.get("raw", [])
        return result if isinstance(result, list) else []

    def extract_table(self, selector: str) -> List[Dict[str, str]]:
        """Extract table data as list of row dicts."""
        result = self.evaluate_script(f"""
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
        """)
        if isinstance(result, dict):
            return result.get("raw", [])
        return result if isinstance(result, list) else []

    def extract_links(self, selector: str = "a") -> List[Dict[str, str]]:
        """Extract links from elements matching CSS selector."""
        result = self.evaluate_script(f"""
            const links = document.querySelectorAll('{selector}');
            return Array.from(links).map(link => ({{
                text: link.textContent.trim(),
                href: link.href,
                title: link.title || ''
            }}));
        """)
        if isinstance(result, dict):
            return result.get("raw", [])
        return result if isinstance(result, list) else []

    def extract_by_config(self, config: ScrapeConfig) -> ScrapeResult:
        """Extract data using configuration-driven approach."""
        start_time = time.time()
        result = ScrapeResult(url=config.url)

        try:
            # Navigate and wait
            self.navigate(config.url)

            if config.auth:
                self._handle_auth(config.auth)

            if config.wait_for:
                self.wait_for(config.wait_for, config.timeout)

            if config.scroll:
                self.scroll_to_bottom()

            # Custom JS extraction if provided
            if config.js_extract:
                data = self.evaluate_script(config.js_extract)
                if isinstance(data, dict) and "raw" in data:
                    data = data["raw"]
                if isinstance(data, list):
                    result.data = data
                else:
                    result.data = [data]
                return result

            # Config-driven extraction
            all_data = []
            for page_num in range(1, config.max_pages + 1):
                items = self._extract_items(config.items_selector, config.fields)
                all_data.extend(items)

                # Pagination
                if config.pagination and page_num < config.max_pages:
                    if not self._next_page(config.pagination):
                        break

            result.data = all_data
            result.metadata["pages_scraped"] = page_num
            result.metadata["total_items"] = len(all_data)

        except Exception as e:
            result.errors.append(str(e))

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def _extract_items(self, items_selector: str, fields: Dict[str, str]) -> List[Dict[str, Any]]:
        """Extract items using selector and field mappings."""
        js_fields = json.dumps(fields)
        result = self.evaluate_script(f"""
            const items = document.querySelectorAll('{items_selector}');
            const fieldMap = {js_fields};
            return Array.from(items).map(item => {{
                const obj = {{}};
                for (const [field, selector] of Object.entries(fieldMap)) {{
                    const el = item.querySelector(selector);
                    if (el) {{
                        // Handle different element types
                        if (el.tagName === 'A') {{
                            obj[field] = {{
                                text: el.textContent.trim(),
                                href: el.href,
                                title: el.title || ''
                            }};
                        }} else if (el.tagName === 'IMG') {{
                            obj[field] = {{
                                src: el.src,
                                alt: el.alt || ''
                            }};
                        }} else {{
                            obj[field] = el.textContent.trim();
                        }}
                    }} else {{
                        obj[field] = null;
                    }}
                }}
                return obj;
            }});
        """)
        if isinstance(result, dict) and "raw" in result:
            result = result["raw"]
        return result if isinstance(result, list) else []

    def _next_page(self, pagination_selector: str) -> bool:
        """Click next page button and wait."""
        try:
            snapshot = self.take_snapshot()
            uid = self.find_uid(snapshot, pagination_selector)
            if uid:
                self.click_uid(uid)
                time.sleep(1)
                return True
            return False
        except Exception:
            return False

    def _handle_auth(self, auth: Dict[str, str]):
        """Handle login with auth config."""
        if auth.get("url"):
            self.navigate(auth["url"])

        snapshot = self.take_snapshot()

        # Fill username
        if auth.get("user_selector") and auth.get("username"):
            uid = self.find_uid(snapshot, auth["user_selector"])
            if uid:
                self.click_uid(uid)
                time.sleep(0.2)
                self.type_text(auth["username"])

        # Fill password
        if auth.get("pass_selector") and auth.get("password"):
            uid = self.find_uid(snapshot, auth["pass_selector"])
            if uid:
                self.click_uid(uid)
                time.sleep(0.2)
                self.type_text(auth["password"])

        # Submit
        if auth.get("submit_selector"):
            uid = self.find_uid(snapshot, auth["submit_selector"])
            if uid:
                self.click_uid(uid)
                time.sleep(1)

    def scrape(self) -> ScrapeResult:
        """Main scrape method - override in subclasses."""
        return self.extract_by_config(self.config)

    def close(self):
        """Close MCP connection."""
        self.mcp.close()


# -----------------------------------------------------------------------------
#  Example Scraper Subclasses
# -----------------------------------------------------------------------------

class NewsScraperExample(WebScraper):
    """Example news site scraper."""

    def scrape(self) -> ScrapeResult:
        """Scrape news articles."""
        return self.extract_by_config(self.config)


class EcommerceScraperExample(WebScraper):
    """Example e-commerce product page scraper."""

    def scrape(self) -> ScrapeResult:
        """Scrape product listings."""
        return self.extract_by_config(self.config)


# -----------------------------------------------------------------------------
#  Scraper Registry (for LLM extension)
# -----------------------------------------------------------------------------

SCRAPERS: Dict[str, type] = {
    "news": NewsScraperExample,
    "ecommerce": EcommerceScraperExample,
}


def register_scraper(name: str, scraper_class: type):
    """Register a custom scraper class."""
    SCRAPERS[name] = scraper_class


def get_scraper(name: str, config: ScrapeConfig) -> WebScraper:
    """Get scraper instance by name."""
    if name not in SCRAPERS:
        raise ValueError(f"Unknown scraper: {name}")
    return SCRAPERS[name](config)


# -----------------------------------------------------------------------------
#  Standalone Functions
# -----------------------------------------------------------------------------

def scrape_url(url: str, config: Optional[ScrapeConfig] = None) -> ScrapeResult:
    """
    Standalone function to scrape a URL.

    USAGE:
        config = ScrapeConfig(url="https://example.com", items_selector=".item", fields={"title": ".title"})
        result = scrape_url(config.url, config)
        print(result.data)
    """
    if config is None:
        config = ScrapeConfig(url=url, items_selector="body", fields={})

    scraper = WebScraper(config)
    try:
        scraper.connect()
        return scraper.scrape()
    finally:
        scraper.close()


def scrape_with_scraper(scraper_name: str, config: ScrapeConfig) -> ScrapeResult:
    """
    Scrape using a registered scraper.

    USAGE:
        config = ScrapeConfig(url="https://news.com", items_selector=".article", fields={"headline": ".headline"})
        result = scrape_with_scraper("news", config)
    """
    scraper = get_scraper(scraper_name, config)
    try:
        scraper.connect()
        return scraper.scrape()
    finally:
        scraper.close()


# -----------------------------------------------------------------------------
#  CLI Interface
# -----------------------------------------------------------------------------

def main():
    """CLI interface for testing."""
    import argparse

    parser = argparse.ArgumentParser(description="CDP Web Scraper")
    parser.add_argument("url", help="URL to scrape")
    parser.add_argument("--items", required=True, help="CSS selector for items")
    parser.add_argument("--fields", required=True, help="Field mappings (JSON: {\"title\": \".title\"})")
    parser.add_argument("--pages", type=int, default=1, help="Max pages to scrape")
    parser.add_argument("--scroll", action="store_true", help="Scroll to bottom")
    parser.add_argument("--output", help="Output JSON file")

    args = parser.parse_args()

    try:
        fields = json.loads(args.fields)
    except json.JSONDecodeError:
        print("Error: --fields must be valid JSON")
        return 1

    config = ScrapeConfig(
        url=args.url,
        items_selector=args.items,
        fields=fields,
        max_pages=args.pages,
        scroll=args.scroll,
    )

    result = scrape_url(args.url, config)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"Saved to {args.output}")
    else:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
