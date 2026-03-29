"""
Telegram Bot Token Validator
Validates bot tokens via Telegram API before deployment.
"""
import requests
from typing import Tuple, Dict
from utils.logger import logger


def validate_telegram_token(token: str) -> Tuple[bool, Dict]:
    """
    Validate Telegram bot token via getMe API.
    
    Args:
        token: Telegram bot token to validate
    
    Returns:
        Tuple of (is_valid, info_dict)
        - If valid: (True, {"bot_id": int, "username": str, "first_name": str})
        - If invalid: (False, {"error": str})
    
    Security:
        - NEVER logs the token
        - 10 second timeout
        - Returns error message without exposing token
    """
    try:
        # Validate token format (basic check)
        if not token or ":" not in token:
            return False, {"error": "Invalid token format"}
        
        # Call Telegram getMe API
        url = f"https://api.telegram.org/bot{token}/getMe"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get("ok"):
                bot_info = data.get("result", {})
                return True, {
                    "bot_id": bot_info.get("id"),
                    "username": bot_info.get("username"),
                    "first_name": bot_info.get("first_name"),
                    "is_bot": bot_info.get("is_bot", True)
                }
            else:
                error_code = data.get("error_code", "unknown")
                description = data.get("description", "Unknown error")
                return False, {"error": f"Telegram API error {error_code}: {description}"}
        
        elif response.status_code == 401:
            return False, {"error": "Invalid bot token (unauthorized)"}
        
        elif response.status_code == 404:
            return False, {"error": "Bot not found or token invalid"}
        
        else:
            return False, {"error": f"HTTP {response.status_code}: {response.text[:100]}"}
    
    except requests.exceptions.Timeout:
        logger.error("Telegram API timeout during token validation")
        return False, {"error": "Request timeout - Telegram API unreachable"}
    
    except requests.exceptions.ConnectionError:
        logger.error("Connection error during token validation")
        return False, {"error": "Connection error - check network connectivity"}
    
    except requests.exceptions.RequestException as e:
        # Log error type but NEVER log the token
        logger.error(f"Request error during token validation: {type(e).__name__}")
        return False, {"error": f"Request failed: {str(e)[:100]}"}
    
    except Exception as e:
        logger.error(f"Unexpected error during token validation: {type(e).__name__}")
        return False, {"error": f"Validation failed: {str(e)[:100]}"}
