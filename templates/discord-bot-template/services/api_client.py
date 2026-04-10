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
