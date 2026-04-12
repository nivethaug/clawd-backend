#!/usr/bin/env python3
"""
Scheduler Validator - Validates executor.py exists and has correct interface.
Also validates sender channel credentials (Telegram, Discord, Email, API).
"""

import os
import smtplib
from pathlib import Path
from typing import Tuple, Dict, Optional

import requests
from dotenv import load_dotenv

from utils.logger import logger

# Load backend .env for SMTP defaults
load_dotenv()


def validate_scheduler_project(project_path: str) -> Tuple[bool, dict]:
    """
    Validate a scheduler project has the required structure.

    Args:
        project_path: Path to scheduler/ directory

    Returns:
        (is_valid, info_dict)
    """
    path = Path(project_path)
    info = {"project_path": str(path)}

    # Check executor.py exists
    executor_path = path / "scheduler" / "executor.py"
    if not executor_path.exists():
        executor_path = path / "executor.py"

    if not executor_path.exists():
        info["error"] = "executor.py not found"
        return False, info

    # Check execute_task function exists
    content = executor_path.read_text()
    if "def execute_task" not in content:
        info["error"] = "execute_task function not found in executor.py"
        return False, info

    info["executor_path"] = str(executor_path)
    info["has_execute_task"] = True

    logger.info(f"✅ Scheduler project validated: {project_path}")
    return True, info


def validate_scheduler_channels(
    telegram_bot_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    discord_webhook_url: Optional[str] = None,
    email_to: Optional[str] = None,
    api_endpoint: Optional[str] = None,
) -> Dict:
    """
    Validate scheduler sender channel credentials.

    Each provided channel is validated independently. Only channels with
    non-empty values are tested.

    Args:
        telegram_bot_token: Telegram bot token to validate
        telegram_chat_id: Telegram chat ID to validate with bot
        discord_webhook_url: Discord webhook URL to validate
        email_to: Email address to send test to (uses shared SMTP)
        api_endpoint: API endpoint URL to validate

    Returns:
        {
            "valid": bool,  # True if at least one channel passed
            "channels": {
                "telegram": {"valid": bool, "bot_username": str} | None,
                "discord": {"valid": bool} | None,
                "email": {"valid": bool, "to": str} | None,
                "api": {"valid": bool} | None
            }
        }
    """
    channels = {}

    # --- Telegram channel ---
    if telegram_bot_token:
        result = _validate_telegram_channel(telegram_bot_token, telegram_chat_id)
        channels["telegram"] = result
    else:
        channels["telegram"] = None

    # --- Discord channel ---
    if discord_webhook_url:
        result = _validate_discord_channel(discord_webhook_url)
        channels["discord"] = result
    else:
        channels["discord"] = None

    # --- Email channel ---
    if email_to:
        result = _validate_email_channel(email_to)
        channels["email"] = result
    else:
        channels["email"] = None

    # --- API channel ---
    if api_endpoint:
        result = _validate_api_channel(api_endpoint)
        channels["api"] = result
    else:
        channels["api"] = None

    # At least one channel must be provided AND valid
    any_valid = any(
        ch is not None and ch.get("valid") is True
        for ch in channels.values()
    )

    return {"valid": any_valid, "channels": channels}


def _validate_telegram_channel(bot_token: str, chat_id: Optional[str] = None) -> Dict:
    """Validate Telegram bot token via getMe API."""
    try:
        from services.telegram.validator import validate_telegram_token
        is_valid, info = validate_telegram_token(bot_token)

        if is_valid:
            result = {"valid": True, "bot_username": info.get("username", "")}

            # Optionally validate chat_id if provided
            if chat_id:
                try:
                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    # Send a test message and delete it immediately
                    resp = requests.post(url, json={
                        'chat_id': chat_id,
                        'text': '🔍 Credential verification test (auto-deleted)'
                    }, timeout=10)
                    data = resp.json()

                    if data.get('ok'):
                        # Try to delete the test message
                        msg_id = data.get('result', {}).get('message_id')
                        if msg_id:
                            requests.post(
                                f"https://api.telegram.org/bot{bot_token}/deleteMessage",
                                json={'chat_id': chat_id, 'message_id': msg_id},
                                timeout=5
                            )
                        result["chat_id_valid"] = True
                    else:
                        result["chat_id_valid"] = False
                        result["chat_id_error"] = data.get('description', 'unknown error')
                except Exception as e:
                    result["chat_id_valid"] = False
                    result["chat_id_error"] = str(e)

            return result
        else:
            return {"valid": False, "error": info.get("error", "Invalid token")}

    except ImportError:
        # Fallback: direct API call
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getMe"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get('ok'):
                bot_info = data.get('result', {})
                return {"valid": True, "bot_username": bot_info.get('username', '')}
            return {"valid": False, "error": data.get('description', 'Invalid token')}
        except Exception as e:
            return {"valid": False, "error": str(e)}


def _validate_discord_channel(webhook_url: str) -> Dict:
    """Validate Discord webhook by sending a test message."""
    try:
        resp = requests.post(webhook_url, json={
            'content': '🔍 Credential verification test',
            'flags': 64  # EPHEMERAL - only visible to webhook (silently ignored by webhooks)
        }, timeout=10)

        if resp.status_code == 204 or resp.status_code == 200:
            return {"valid": True}
        return {"valid": False, "error": f"HTTP {resp.status_code}: {resp.text[:100]}"}
    except requests.exceptions.Timeout:
        return {"valid": False, "error": "Request timeout"}
    except requests.exceptions.ConnectionError:
        return {"valid": False, "error": "Connection failed"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


def _validate_email_channel(email_to: str) -> Dict:
    """Validate email by sending test email via shared SMTP."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.hostinger.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER", "support@dreambigwithai.com")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_from = os.getenv("SMTP_FROM", "dreamagent@dreambigwithai.com")

    try:
        from email.mime.text import MIMEText

        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
            if smtp_pass:
                server.login(smtp_user, smtp_pass)

            msg = MIMEText("This is a credential verification test from DreamPilot. If you received this, email sending works correctly.")
            msg['Subject'] = '[DreamPilot] Credential Verification Test'
            msg['From'] = smtp_from
            msg['To'] = email_to

            server.sendmail(smtp_from, email_to, msg.as_string())

        return {"valid": True, "to": email_to}
    except smtplib.SMTPAuthenticationError as e:
        return {"valid": False, "error": f"SMTP auth failed: {e}"}
    except smtplib.SMTPException as e:
        return {"valid": False, "error": f"SMTP error: {e}"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


def _validate_api_channel(url: str) -> Dict:
    """Validate API endpoint by checking URL is reachable."""
    try:
        resp = requests.head(url, timeout=10, allow_redirects=True)
        return {"valid": True, "status": resp.status_code}
    except requests.exceptions.Timeout:
        return {"valid": False, "error": "Request timeout"}
    except requests.exceptions.ConnectionError:
        return {"valid": False, "error": "Connection failed"}
    except Exception as e:
        return {"valid": False, "error": str(e)}
