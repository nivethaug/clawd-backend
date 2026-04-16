"""
API Client module.
ALL external API calls go here.
Easy to modify by AI agents.

# DreamAgent: AI can add helper functions here for dynamic integrations
"""

import requests
from utils.logger import logger
from config import API_TIMEOUT


# ============================================================================
# UTILITY FUNCTIONS (Do not modify)
# ============================================================================

def fetch_json(url: str, params: dict = None, timeout: int = API_TIMEOUT) -> dict:
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
        logger.error(f"API timeout: {url}")
        return {"success": False, "error": "Request timeout"}
    except requests.exceptions.RequestException as e:
        logger.error(f"API error: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {"success": False, "error": "Failed to fetch data"}


def safe_get(data: dict, *keys, default=None):
    """
    Safely get nested dictionary value.
    
    Args:
        data: Dictionary to search
        *keys: Nested keys
        default: Default value if key not found
    
    Returns:
        Value at nested key or default
    
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
        url = f"https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": coin_id,
            "vs_currencies": currency
        }
        
        response = requests.get(url, params=params, timeout=API_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        if coin_id in data and currency in data[coin_id]:
            return {
                "success": True,
                "price": data[coin_id][currency],
                "coin": coin_id,
                "currency": currency
            }
        else:
            return {"success": False, "error": "Coin not found"}
            
    except requests.exceptions.Timeout:
        logger.error(f"API timeout for {coin_id}")
        return {"success": False, "error": "Request timeout"}
    except requests.exceptions.RequestException as e:
        logger.error(f"API error: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        # Safety net - never crash the bot
        logger.error(f"Unexpected error in get_crypto_price: {e}")
        return {"success": False, "error": "Failed to fetch data"}


def get_weather(city: str) -> dict:
    """
    Fetch weather data (placeholder for future implementation).

    Args:
        city: City name

    Returns:
        dict with weather data or error info
    """
    # TODO: Implement with OpenWeatherMap or similar
    logger.info(f"Weather request for {city} - not implemented")
    return {
        "success": False,
        "error": "Weather API not configured yet"
    }


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
