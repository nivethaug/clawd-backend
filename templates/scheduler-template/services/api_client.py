#!/usr/bin/env python3
"""
API Client module.
ALL external API calls go here.
Easy to modify by AI agents.

AI agents can add helper functions here for dynamic integrations.
"""

import requests

REQUEST_TIMEOUT = 10


# ============================================================================
# UTILITY FUNCTIONS (Do not modify)
# ============================================================================

def fetch_json(url: str, params: dict = None, timeout: int = REQUEST_TIMEOUT) -> dict:
    """
    Generic JSON fetcher for public APIs.

    Args:
        url: API endpoint URL
        params: Optional query parameters
        timeout: Request timeout in seconds

    Returns:
        dict with success status and data or error
    """
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timeout"}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": "Failed to fetch data"}


def safe_get(data: dict, *keys, default=None):
    """
    Safely get nested dictionary value.

    Example:
        safe_get(response, "data", "price", default=0)
    """
    for key in keys:
        try:
            data = data[key]
        except (KeyError, TypeError):
            return default
    return data


# ============================================================================
# API HELPER FUNCTIONS (AI can add more below)
# ============================================================================

def get_crypto_price(coin_id: str = "bitcoin", currency: str = "usd") -> dict:
    """
    Fetch cryptocurrency price from CoinGecko API.

    Args:
        coin_id: Coin identifier (e.g., 'bitcoin', 'ethereum')
        currency: Target currency (e.g., 'usd', 'eur')

    Returns:
        dict with price data or error info
    """
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": coin_id, "vs_currencies": currency}

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if coin_id in data and currency in data[coin_id]:
            return {
                "success": True,
                "price": data[coin_id][currency],
                "coin": coin_id,
                "currency": currency
            }
        return {"success": False, "error": "Coin not found"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_weather(latitude: float = 40.71, longitude: float = -74.01) -> dict:
    """
    Fetch weather data from Open-Meteo API.

    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate

    Returns:
        dict with weather data or error info
    """
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current_weather": True
        }

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        weather = data.get("current_weather", {})
        return {
            "success": True,
            "temperature": weather.get("temperature"),
            "windspeed": weather.get("windspeed"),
            "weathercode": weather.get("weathercode")
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_news(query: str = "technology", page: int = 1) -> dict:
    """
    Fetch news from Hacker News API.

    Returns:
        dict with top story titles
    """
    try:
        url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        story_ids = response.json()[:5]

        stories = []
        for sid in story_ids:
            story_resp = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                timeout=REQUEST_TIMEOUT
            )
            if story_resp.ok:
                stories.append(story_resp.json().get("title", ""))

        return {"success": True, "stories": stories}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# WEB SCRAPER USAGE EXAMPLE (Commented)
# ============================================================================

# The web_scraper.py module provides Chrome DevTools Protocol (CDP) scraping
# capabilities. Here's how to use it in your scheduler:
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
