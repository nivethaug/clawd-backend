#!/usr/bin/env python3
"""
API Client module.
ALL external API calls go here.
Easy to modify by AI agents.

AI agents can add helper functions here for dynamic integrations.
"""

import requests
from config import SCHEDULER_INTERVAL

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
