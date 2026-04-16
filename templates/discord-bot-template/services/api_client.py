#!/usr/bin/env python3
"""
API Client - External API calls.

AI agents can modify this file to add new API integrations.
All external HTTP requests go through this module.
"""
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger('services.api_client')

# API endpoints
API_URLS = {
    "bitcoin": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
}

# Default timeout for all requests
REQUEST_TIMEOUT = 10


def fetch_data(api_name: str) -> Any:
    """
    Fetch data from an external API.

    Args:
        api_name: Key name from API_URLS dict

    Returns:
        Parsed response data

    Raises:
        ValueError: If api_name not found
        requests.RequestException: If request fails
    """
    url = API_URLS.get(api_name)
    if not url:
        raise ValueError(f"Unknown API: {api_name}")

    logger.info(f"API request: {api_name} -> {url[:80]}...")
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    logger.info(f"API response: {api_name} -> {str(data)[:100]}")
    return data


def fetch_bitcoin_price() -> float:
    """
    Fetch current Bitcoin price in USD.

    Returns:
        Bitcoin price as float
    """
    data = fetch_data("bitcoin")
    return data["bitcoin"]["usd"]


def get_json(url: str, params: Optional[Dict] = None) -> Dict:
    """
    Generic GET request returning JSON.

    Args:
        url: Request URL
        params: Optional query parameters

    Returns:
        JSON response as dict
    """
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def post_json(url: str, data: Optional[Dict] = None) -> Dict:
    """
    Generic POST request returning JSON.

    Args:
        url: Request URL
        data: Optional request body

    Returns:
        JSON response as dict
    """
    response = requests.post(url, json=data, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


# ============================================================================
# WEB SCRAPER USAGE EXAMPLE (Commented)
# ============================================================================

# The web_scraper.py module provides Chrome DevTools Protocol (CDP) scraping
# capabilities. Here's how to use it in your bot:
#
# from services.web_scraper import WebScraper, ScrapeConfig, scrape_url
# from services.web_scraper import register_scraper, get_scraper
#
# # Example 1: Simple standalone scrape
# def scrape_example_site(url: str) -> dict:
#     """Scrape a website with simple item list."""
#     config = ScrapeConfig(
#         url=url,
#         items_selector=".article",  # CSS selector for list items
#         fields={
#             "title": "h2",           # Article title
#             "link": "a",             # Article link
#             "summary": ".summary"     # Article summary
#         },
#         max_pages=5,                 # Scrape up to 5 pages
#         scroll=True                  # Scroll for lazy-loaded content
#     )
#     result = scrape_url(url, config)
#     return {
#         "success": len(result.errors) == 0,
#         "data": result.data,
#         "metadata": result.metadata,
#         "errors": result.errors
#     }
#
# # Example 2: Custom scraper subclass
# class MyCustomScraper(WebScraper):
#     """Custom scraper for specific website."""
#
#     def scrape(self) -> ScrapeResult:
#         """Custom scrape logic."""
#         self.navigate(self.config.url)
#         self.wait_for_text("loaded")
#         return self.extract_by_config(self.config)
#
# # Register custom scraper (optional, for LLM extensibility)
# register_scraper("custom", MyCustomScraper)
#
# # Example 3: Use registered scraper
# def scrape_with_custom(name: str, url: str) -> dict:
#     """Scrape using a registered scraper."""
#     config = ScrapeConfig(
#         url=url,
#         items_selector=".item",
#         fields={"title": ".title"}
#     )
#     result = scrape_with_scraper(name, config)
#     return {
#         "success": len(result.errors) == 0,
#         "data": result.data
#     }
#
# NOTE: The web_scraper requires Chrome/Edge with remote debugging port 9222.
# The scraper will automatically launch Chrome if not running.
#
# For more examples, see:
# - NewsScraperExample
# - EcommerceScraperExample
# (at the bottom of web_scraper.py)
