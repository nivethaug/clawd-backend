"""
API Client module.
ALL external API calls go here.
Easy to modify by AI agents.
"""

import requests
from utils.logger import logger
from config import API_TIMEOUT


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
