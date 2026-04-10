"""
Discord Bot Token Validator
Validates bot tokens via Discord API before deployment.
"""
import requests
from typing import Tuple, Dict
from utils.logger import logger


# Minimal permissions needed for bot commands (Send Messages, Read Message History, Use Application Commands)
# Calculated using Discord's permission calculator
BOT_PERMISSIONS = 277025770560  # SendMessages + ReadMessageHistory + UseApplicationCommands

# Privileged intents required
REQUIRED_INTENTS = ["MESSAGE CONTENT"]


def validate_discord_token(token: str) -> Tuple[bool, Dict]:
    """
    Validate Discord bot token via /users/@me API.

    Args:
        token: Discord bot token to validate

    Returns:
        Tuple of (is_valid, info_dict)
        - If valid: (True, {"bot_id": str, "username": str, "global_name": str, "invite_url": str})
        - If invalid: (False, {"error": str})

    Security:
        - NEVER logs the token
        - 10 second timeout
        - Returns error message without exposing token
    """
    try:
        # Validate token format (Discord tokens contain periods)
        if not token or "." not in token:
            return False, {"error": "Invalid token format"}

        # Call Discord API to verify token
        url = "https://discord.com/api/v10/users/@me"
        headers = {"Authorization": f"Bot {token}"}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            bot_id = data.get("id")

            # Generate invite URL with correct permissions
            invite_url = (
                f"https://discord.com/api/oauth2/authorize?client_id={bot_id}"
                f"&permissions={BOT_PERMISSIONS}&scope=bot"
            )

            return True, {
                "bot_id": bot_id,
                "username": data.get("username"),
                "global_name": data.get("global_name", data.get("username")),
                "is_bot": data.get("bot", True),
                "invite_url": invite_url
            }

        elif response.status_code == 401:
            return False, {"error": "Invalid bot token (unauthorized)"}

        elif response.status_code == 403:
            return False, {"error": "Token valid but bot lacks required scopes"}

        else:
            return False, {"error": f"HTTP {response.status_code}: {response.text[:100]}"}

    except requests.exceptions.Timeout:
        logger.error("Discord API timeout during token validation")
        return False, {"error": "Request timeout - Discord API unreachable"}

    except requests.exceptions.ConnectionError:
        logger.error("Connection error during token validation")
        return False, {"error": "Connection error - check network connectivity"}

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error during token validation: {type(e).__name__}")
        return False, {"error": f"Request failed: {str(e)[:100]}"}

    except Exception as e:
        logger.error(f"Unexpected error during token validation: {type(e).__name__}")
        return False, {"error": f"Validation failed: {str(e)[:100]}"}
