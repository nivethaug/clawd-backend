#!/usr/bin/env python3
"""
Web Scraper Test Suite

Tests the CDP Web Scraper functionality including:
- Configuration (ScrapeConfig, ScrapeResult)
- MCPClient connection
- Navigation and page interaction
- Data extraction methods
- Example scrapers
- Config-driven extraction

Usage:
    python tests/test_web_scraper.py                # Test all functionality
    python tests/test_web_scraper.py --connection    # Test MCP connection only
    python tests/test_web_scraper.py --navigation    # Test navigation only
    python tests/test_web_scraper.py --extraction   # Test extraction only
    python tests/test_web_scraper.py --scrapers     # Test example scrapers
    python tests/test_web_scraper.py --url <url>    # Test specific URL

Requirements:
    - Chrome/Edge browser with remote debugging port 9222
    - Or set CHROME_PATH environment variable
    - Network connection for live site testing
"""

import sys
import os
import json
import time
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.web_scraper import (
    WebScraper,
    ScrapeConfig,
    ScrapeResult,
    scrape_url,
    register_scraper,
    get_scraper,
    SCRAPERS,
    MCPClient,
)


# ---------------------------------------------------------------------------
# Test Configuration
# ---------------------------------------------------------------------------

# Test URLs (public sites that should be accessible)
TEST_URLS = {
    "example": "https://example.com",
    "httpbin": "https://httpbin.org/html",
    "wikipedia": "https://en.wikipedia.org/wiki/List_of_cities",
    "httpbin_forms": "https://httpbin.org/forms/post",
}

# Default test URL
DEFAULT_TEST_URL = os.getenv("TEST_SCRAPER_URL", TEST_URLS["httpbin"])


# ---------------------------------------------------------------------------
# Test Functions
# ---------------------------------------------------------------------------

def test_config() -> dict:
    """Test ScrapeConfig and ScrapeResult dataclasses."""
    print(f"\n{'='*60}")
    print(f"TEST: Configuration (ScrapeConfig, ScrapeResult)")
    print(f"{'='*60}")

    try:
        # Test ScrapeConfig
        config = ScrapeConfig(
            url=DEFAULT_TEST_URL,
            items_selector="body",
            fields={"title": "h1"},
            max_pages=2,
            scroll=True,
            wait_for=["loaded"],
        )

        assert config.url == DEFAULT_TEST_URL
        assert config.items_selector == "body"
        assert config.max_pages == 2
        assert config.scroll is True
        print(f"  [PASS] ScrapeConfig created successfully")

        # Test ScrapeResult
        result = ScrapeResult(url=DEFAULT_TEST_URL)
        result.data = [{"test": "data"}]
        result.metadata = {"pages": 1}
        result.errors = []

        assert result.url == DEFAULT_TEST_URL
        assert len(result.data) == 1
        assert len(result.errors) == 0

        # Test to_dict()
        result_dict = result.to_dict()
        assert isinstance(result_dict, dict)
        assert "url" in result_dict
        assert "data" in result_dict
        assert "metadata" in result_dict
        print(f"  [PASS] ScrapeResult created and serialized successfully")

        print(f"  Result: SUCCESS")
        return {"test": "config", "status": "success"}

    except Exception as e:
        print(f"  Result: FAILED - {e}")
        return {"test": "config", "status": "failed", "error": str(e)}


def test_registry() -> dict:
    """Test scraper registry and registration."""
    print(f"\n{'='*60}")
    print(f"TEST: Scraper Registry")
    print(f"{'='*60}")

    try:
        # Check default scrapers exist
        assert "news" in SCRAPERS
        assert "ecommerce" in SCRAPERS
        print(f"  [PASS] Default scrapers registered: {list(SCRAPERS.keys())}")

        # Test get_scraper()
        config = ScrapeConfig(url=DEFAULT_TEST_URL, items_selector="body", fields={})
        scraper = get_scraper("news", config)
        assert scraper is not None
        assert isinstance(scraper, WebScraper)
        print(f"  [PASS] get_scraper() works")

        # Test register_scraper()
        class TestScraper(WebScraper):
            pass

        register_scraper("test", TestScraper)
        assert "test" in SCRAPERS
        test_scraper = get_scraper("test", config)
        assert isinstance(test_scraper, TestScraper)
        print(f"  [PASS] register_scraper() works")

        print(f"  Result: SUCCESS")
        return {"test": "registry", "status": "success"}

    except Exception as e:
        print(f"  Result: FAILED - {e}")
        return {"test": "registry", "status": "failed", "error": str(e)}


def test_connection() -> dict:
    """Test MCPClient connection to Chrome."""
    print(f"\n{'='*60}")
    print(f"TEST: MCPClient Connection")
    print(f"{'='*60}")
    print(f"  Note: This test will launch Chrome if not running on port 9222")
    print(f"  Note: Chrome will close after test completes")

    try:
        mcp = MCPClient()

        print(f"  [STEP] Starting MCP server...")
        mcp.start_server()
        print(f"  [PASS] MCP server started")

        print(f"  [STEP] Listing pages...")
        result = mcp.call_tool("list_pages", {})
        print(f"  [PASS] Pages listed successfully")

        print(f"  [STEP] Creating new page...")
        page_result = mcp.call_tool("new_page", {"url": "about:blank"})
        page_id = page_result.get("pageId")
        print(f"  [PASS] New page created: {page_id}")

        print(f"  [STEP] Taking snapshot...")
        snapshot = mcp.call_tool("take_snapshot", {})
        snapshot_text = snapshot.get("text", "")
        print(f"  [PASS] Snapshot taken ({len(snapshot_text)} chars)")

        print(f"  [STEP] Evaluating script...")
        script_result = mcp.call_tool("evaluate_script", {
            "function": "() => { return {title: document.title, url: window.location.href }; }"
        })
        print(f"  [PASS] Script evaluated: {script_result.get('text', '')[:100]}")

        mcp.close()
        print(f"  [PASS] MCP connection closed")

        print(f"  Result: SUCCESS")
        return {"test": "connection", "status": "success"}

    except Exception as e:
        print(f"  Result: FAILED - {e}")
        return {"test": "connection", "status": "failed", "error": str(e)}


def test_navigation(url: str = None) -> dict:
    """Test navigation to a URL."""
    test_url = url or DEFAULT_TEST_URL

    print(f"\n{'='*60}")
    print(f"TEST: Navigation")
    print(f"{'='*60}")
    print(f"  Target URL: {test_url}")

    try:
        config = ScrapeConfig(
            url=test_url,
            items_selector="body",
            fields={},
            wait_for=["body"],  # Wait for body to exist
        )

        scraper = WebScraper(config)

        print(f"  [STEP] Connecting...")
        scraper.connect()
        print(f"  [PASS] Connected")

        print(f"  [STEP] Navigating to {test_url}...")
        success = scraper.navigate(test_url)
        assert success is True
        print(f"  [PASS] Navigated successfully")

        print(f"  [STEP] Taking snapshot...")
        snapshot = scraper.take_snapshot()
        print(f"  [PASS] Snapshot taken ({len(snapshot)} chars)")

        print(f"  [STEP] Getting page title...")
        title = scraper.extract_text("title")
        print(f"  [PASS] Page title: {title}")

        scraper.close()
        print(f"  [PASS] Connection closed")

        print(f"  Result: SUCCESS")
        return {"test": "navigation", "status": "success", "url": test_url, "title": title}

    except Exception as e:
        print(f"  Result: FAILED - {e}")
        return {"test": "navigation", "status": "failed", "error": str(e), "url": test_url}


def test_extraction(url: str = None) -> dict:
    """Test data extraction methods."""
    test_url = url or DEFAULT_TEST_URL

    print(f"\n{'='*60}")
    print(f"TEST: Data Extraction")
    print(f"{'='*60}")
    print(f"  Target URL: {test_url}")

    try:
        config = ScrapeConfig(
            url=test_url,
            items_selector="body",
            fields={},
        )

        scraper = WebScraper(config)
        scraper.connect()
        scraper.navigate(test_url)

        # Test extract_text()
        print(f"  [STEP] Testing extract_text()...")
        title = scraper.extract_text("title")
        print(f"  [PASS] extract_text() returned: {title[:50] if title else 'None'}...")

        # Test extract_list()
        print(f"  [STEP] Testing extract_list()...")
        links = scraper.extract_list("a")
        print(f"  [PASS] extract_list() found {len(links)} links")

        # Test extract_links()
        print(f"  [STEP] Testing extract_links()...")
        link_objs = scraper.extract_links("a")
        print(f"  [PASS] extract_links() found {len(link_objs)} link objects")

        # Test evaluate_script()
        print(f"  [STEP] Testing evaluate_script()...")
        result = scraper.evaluate_script("return document.title;")
        print(f"  [PASS] evaluate_script() returned: {str(result)[:50]}...")

        scraper.close()

        print(f"  Result: SUCCESS")
        return {
            "test": "extraction",
            "status": "success",
            "url": test_url,
            "links_found": len(links),
            "title": title
        }

    except Exception as e:
        print(f"  Result: FAILED - {e}")
        return {"test": "extraction", "status": "failed", "error": str(e), "url": test_url}


def test_config_driven(url: str = None) -> dict:
    """Test config-driven extraction."""
    test_url = url or TEST_URLS["httpbin"]

    print(f"\n{'='*60}")
    print(f"TEST: Config-Driven Extraction")
    print(f"{'='*60}")
    print(f"  Target URL: {test_url}")

    try:
        # Use body as item selector to extract page content
        # Then extract various elements from it
        config = ScrapeConfig(
            url=test_url,
            items_selector="body",
            fields={
                "title": "h1",
                "content": "p",
            },
            max_pages=1,
        )

        scraper = WebScraper(config)
        scraper.connect()  # Must connect before scraping
        result = scraper.scrape()
        scraper.close()

        print(f"  [INFO] Data extracted: {len(result.data)} items")
        print(f"  [INFO] Duration: {result.duration_ms:.2f}ms")
        print(f"  [INFO] Errors: {len(result.errors)}")

        if result.errors:
            print(f"  [DEBUG] Errors: {result.errors}")

        if result.data:
            print(f"  [SAMPLE] First item: {json.dumps(result.data[0], indent=2)[:200]}...")

        # Success is defined as running without errors, not necessarily finding items
        # (selectors may not match page structure)
        if len(result.errors) > 0:
            print(f"  Result: FAILED - Errors occurred during extraction")
            return {
                "test": "config_driven",
                "status": "failed",
                "url": test_url,
                "items_extracted": len(result.data),
                "errors": result.errors,
                "duration_ms": result.duration_ms
            }

        print(f"  Result: SUCCESS")
        return {
            "test": "config_driven",
            "status": "success",
            "url": test_url,
            "items_extracted": len(result.data),
            "duration_ms": result.duration_ms
        }

    except Exception as e:
        print(f"  Result: FAILED - {e}")
        return {"test": "config_driven", "status": "failed", "error": str(e), "url": test_url}


def test_scrape_url_standalone(url: str = None) -> dict:
    """Test standalone scrape_url() function."""
    test_url = url or DEFAULT_TEST_URL

    print(f"\n{'='*60}")
    print(f"TEST: Standalone scrape_url() Function")
    print(f"{'='*60}")
    print(f"  Target URL: {test_url}")

    try:
        config = ScrapeConfig(
            url=test_url,
            items_selector="body",
            fields={"title": "h1", "paragraph": "p"},
            max_pages=1,
        )

        result = scrape_url(test_url, config)

        print(f"  [INFO] Data extracted: {len(result.data)} items")
        print(f"  [INFO] Duration: {result.duration_ms:.2f}ms")
        print(f"  [INFO] Errors: {len(result.errors)}")
        print(f"  [INFO] Timestamp: {result.timestamp}")

        assert result.url == test_url
        assert isinstance(result.data, list)
        assert isinstance(result.metadata, dict)
        assert isinstance(result.errors, list)

        print(f"  Result: SUCCESS")
        return {
            "test": "scrape_url_standalone",
            "status": "success",
            "url": test_url,
            "items_extracted": len(result.data),
            "duration_ms": result.duration_ms
        }

    except Exception as e:
        print(f"  Result: FAILED - {e}")
        return {"test": "scrape_url_standalone", "status": "failed", "error": str(e), "url": test_url}


def test_pagination(url: str = None) -> dict:
    """Test pagination support (using a site with multiple items)."""
    test_url = url or TEST_URLS["httpbin"]

    print(f"\n{'='*60}")
    print(f"TEST: Pagination Support")
    print(f"{'='*60}")
    print(f"  Target URL: {test_url}")

    try:
        config = ScrapeConfig(
            url=test_url,
            items_selector="p",
            fields={"text": "p"},
            max_pages=1,  # Single page for this test
        )

        scraper = WebScraper(config)
        scraper.connect()  # Must connect before scraping
        result = scraper.extract_by_config(config)
        scraper.close()

        print(f"  [INFO] Items extracted: {len(result.data)}")
        print(f"  [INFO] Pages scraped: {result.metadata.get('pages_scraped', 'N/A')}")

        print(f"  Result: SUCCESS")
        return {
            "test": "pagination",
            "status": "success",
            "url": test_url,
            "items_extracted": len(result.data),
            "pages_scraped": result.metadata.get("pages_scraped", 1)
        }

    except Exception as e:
        print(f"  Result: FAILED - {e}")
        return {"test": "pagination", "status": "failed", "error": str(e), "url": test_url}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Test Web Scraper functionality")
    parser.add_argument("--config", action="store_true", help="Test configuration only")
    parser.add_argument("--registry", action="store_true", help="Test scraper registry only")
    parser.add_argument("--connection", action="store_true", help="Test MCP connection only")
    parser.add_argument("--navigation", action="store_true", help="Test navigation only")
    parser.add_argument("--extraction", action="store_true", help="Test data extraction only")
    parser.add_argument("--config-driven", action="store_true", help="Test config-driven extraction only")
    parser.add_argument("--scrape-url", action="store_true", help="Test standalone scrape_url() only")
    parser.add_argument("--pagination", action="store_true", help="Test pagination only")
    parser.add_argument("--url", type=str, help="Custom test URL")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    # If no specific test selected, run all (except full scraping which takes time)
    run_all = not (
        args.config or args.registry or args.connection or
        args.navigation or args.extraction or
        args.config_driven or args.scrape_url or args.pagination
    )

    print()
    print("=" * 60)
    print("  WEB SCRAPER TEST SUITE")
    print("=" * 60)
    print(f"  Test URL: {args.url or DEFAULT_TEST_URL}")
    print(f"  Chrome: Will launch on port 9222 if not running")
    print()

    results = []

    # Lightweight tests (no browser)
    if run_all or args.config:
        results.append(test_config())

    if run_all or args.registry:
        results.append(test_registry())

    # Browser-based tests
    if run_all or args.connection:
        results.append(test_connection())

    if run_all or args.navigation:
        results.append(test_navigation(args.url))

    if run_all or args.extraction:
        results.append(test_extraction(args.url))

    if run_all or args.config_driven:
        results.append(test_config_driven(args.url))

    if run_all or args.scrape_url:
        results.append(test_scrape_url_standalone(args.url))

    if run_all or args.pagination:
        results.append(test_pagination(args.url))

    # Summary
    print()
    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in results if r['status'] == 'success')
    failed = sum(1 for r in results if r['status'] == 'failed')

    for r in results:
        icon = {"success": "PASS", "failed": "FAIL"}[r['status']]
        line = f"  [{icon:4}] {r['test']}"
        if r['status'] == 'failed':
            line += f" - {r.get('error', '')[:80]}"
        print(line)

    print(f"\n  Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    print("=" * 60)

    if args.json:
        print(json.dumps(results, indent=2))

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
