#!/usr/bin/env python3
"""
API Client module.
ALL external API calls go here.
Easy to modify by AI agents.

AI agents can add helper functions here for dynamic integrations.
"""

import os

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


def fetch_page(url: str, extract_js: str = None, render: bool = False, timeout: int = 15) -> dict:
    """
    Fetch and extract data from a web page via the platform scraping API.

    Two modes (tiered for performance):
      - render=False (default): Fast HTTP fetch + HTML parsing (~200ms).
        Use for static pages: news, product listings, tables, blogs.
      - render=True: Full Chrome rendering via CDP (~2-5s, JS executes).
        Use for SPAs (React/Vue), infinite scroll, login-required pages.

    Args:
        url: Target URL to scrape
        extract_js: JavaScript extraction expression. Examples:
            "return document.title"
            "return document.querySelector('h1').textContent"
            "return Array.from(document.querySelectorAll('.item')).map(e => e.textContent.trim())"
            If None, returns page title + body text.
        render: If True, use Chrome CDP (slower but handles JS-rendered pages).
        timeout: Request timeout in seconds

    Returns:
        {"success": True, "data": <extracted_data>, "rendered": bool}
        {"success": False, "error": "..."} on failure
    """
    import os
    api_url = os.getenv("BACKEND_URL", "https://api.dreamagent.cloud")
    if not extract_js:
        extract_js = "return document.title"
    try:
        resp = requests.post(
            f"{api_url}/internal/scrape",
            json={"url": url, "extract_js": extract_js, "render": render, "timeout": timeout},
            timeout=timeout + 5,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)}


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


# =========================================================================
# YouTube (OAuth) — uses the DreamAgent-connected YouTube account.
# The platform injects a fresh YOUTUBE_ACCESS_TOKEN automatically when the
# project owner has connected YouTube (Settings → Integrations). NO API
# key, channel ID, or environment variable configuration is needed.
# =========================================================================

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2"


def _youtube_headers() -> dict:
    """Authorization headers from the platform-injected OAuth token."""
    token = os.environ.get("YOUTUBE_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError(
            "YouTube not connected: the project owner must connect YouTube "
            "in DreamAgent → Settings → Integrations (no API key needed)."
        )
    return {"Authorization": f"Bearer {token}"}


def get_youtube_channel() -> dict:
    """The connected user's own channel (id, title, stats)."""
    return _yt_get("/channels", {"part": "snippet,statistics", "mine": "true"})


def _yt_get(path: str, params: dict, base: str = YOUTUBE_API) -> dict:
    resp = requests.get(f"{base}{path}", params=params,
                        headers=_youtube_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_youtube_latest_videos(max_results: int = 10) -> dict:
    """Latest published videos of the connected channel."""
    channel = _yt_get("/channels", {"part": "contentDetails", "mine": "true"})
    uploads_playlist = (
        channel.get("items", [{}])[0]
        .get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )
    if not uploads_playlist:
        return {"items": []}
    return _yt_get("/playlistItems", {
        "part": "snippet,contentDetails",
        "playlistId": uploads_playlist,
        "maxResults": min(max_results, 50),
    })


def get_youtube_video_stats(video_ids: list) -> dict:
    """Views/likes/comments for specific video ids."""
    if not video_ids:
        return {"items": []}
    return _yt_get("/videos", {
        "part": "statistics,snippet",
        "id": ",".join(video_ids[:50]),
    })


def get_youtube_analytics_summary(start_date: str, end_date: str) -> dict:
    """Authorized YouTube Analytics report for the connected channel
    (views, watch time, subscribers gained, average view duration)."""
    return _yt_get(
        "/reports",
        {
            "ids": "mine",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": "views,estimatedMinutesWatched,subscribersGained,averageViewDuration",
        },
        base=YOUTUBE_ANALYTICS_API,
    )


# ============================================================================
# AGENT CAPABILITY LAYER
# ============================================================================

def proxy_call(provider: str, method: str, endpoint: str,
               body: dict = None, params: dict = None, timeout: int = 30) -> dict:
    """Call ANY OAuth-connected integration through the DreamAgent proxy.

    The platform injects the account token server-side — the agent never
    sees credentials. Works for every provider the project owner connected
    (see the capability list in the build prompt).

    Args:
        provider: provider key, e.g. "youtube", "notion", "twitter",
                  "google-sheet", "slack", "github", "discord"
        method:   HTTP verb (GET/POST/PUT/PATCH/DELETE)
        endpoint: path after the provider's base URL, e.g. "2/tweets",
                  "v1/databases/{id}/query", "chat.postMessage"
        body:     JSON body (optional)
        params:   query params (optional)

    Returns:
        {"status": int, "body": str, "headers": {...}} — provider response
        verbatim. Resumable-upload flows: the session URL arrives in
        headers["location"].
    """
    import requests
    import config as _config

    if not _config.SECRET_KEY:
        return {"status": 0, "body": "SECRET_KEY not configured for this project", "headers": {}}

    try:
        r = requests.request(
            method.upper(),
            f"{_config.BACKEND_URL}/api/integrations/proxy",
            headers={
                "Authorization": f"Bearer {_config.SECRET_KEY}",
                "X-Project-Id": str(_config.PROJECT_ID),
                "Content-Type": "application/json",
            },
            json={"provider": provider, "method": method.upper(),
                  "endpoint": endpoint,
                  **({"body": body} if body is not None else {}),
                  **({"params": params} if params else {})},
            timeout=timeout,
        )
    except requests.exceptions.RequestException as e:
        return {"status": 0, "body": f"proxy call failed: {e}", "headers": {}}

    headers = {k.lower(): v for k, v in r.headers.items()}
    return {"status": r.status_code, "body": r.text, "headers": headers}


def state_get() -> dict:
    """Read this agent's persisted cross-run state (JSON). Empty on first run.

    Powers "only when changed" workflows: compare a fetched value against
    state, act only on change, then state_set() the new baseline."""
    import requests
    import config as _config

    try:
        r = requests.get(
            f"{_config.BACKEND_URL}/api/scheduler/projects/{_config.PROJECT_ID}/state",
            timeout=10,
        )
        if r.status_code == 200:
            return (r.json() or {}).get("state") or {}
    except requests.exceptions.RequestException:
        pass
    return {}


def state_set(data: dict) -> bool:
    """Replace this agent's persisted state (full replace — merge first).
    64KB cap enforced server-side."""
    import requests
    import config as _config

    try:
        r = requests.put(
            f"{_config.BACKEND_URL}/api/scheduler/projects/{_config.PROJECT_ID}/state",
            json={"state": data},
            timeout=10,
        )
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


def get_crypto_price_num(coin_id: str = "bitcoin") -> dict:
    """Numeric crypto price (float) — for condition thresholds like
    {"var": "btc_price_num", "op": ">", "value": 100000}."""
    result = get_crypto_price(coin_id)
    if result.get("success"):
        return {"success": True, "value": float(result.get("price", 0))}
    return result
