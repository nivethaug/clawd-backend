"""
Telegram Webhook Registration Service
Registers Telegram bot webhook after successful deployment.
Safe, Optional. Non-blocking.
"""
import os
import time
import threading
import requests
from typing import Tuple
from utils.logger import logger


def register_telegram_webhook(
    bot_token: str,
    domain: str,
    project_id: int
) -> Tuple[bool, str]:
    """
    Register Telegram webhook for bot.
    
    Args:
        bot_token: Telegram bot token
        domain: Webhook domain (e.g., mybot.dreambigwithai.com)
        project_id: Project ID for webhook path
    
    Returns:
        Tuple of (success, message)
    
    Webhook URL Format:
        https://{domain}/bot/{project_id}/webhook
    
    Safety:
        - Non-blocking (won't break deployment if fails)
        - Timeout: 10 seconds
        - No retries
        - Logs success/failure
    """
    try:
        # Validate inputs
        if not bot_token:
            logger.warning("⚠️ No bot token provided - skipping webhook registration")
            return True, "Skipped (no token)"
        
        if not domain:
            logger.warning("⚠️ No domain provided - skipping webhook registration")
            return True, "Skipped (no domain)"
        
        # Build webhook URL (matches nginx /webhook location)
        webhook_url = f"https://{domain}/webhook"
        
        logger.info(f"🔗 Registering Telegram webhook: {webhook_url}")
        
        # Call Telegram setWebhook API
        telegram_api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        
        payload = {
            "url": webhook_url,
            "allowed_updates": ["message", "edited_message", "callback_query"]
        }
        
        logger.info(f"📤 Sending payload to Telegram API: {payload}")
        
        response = requests.post(
            telegram_api_url,
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # Log full API response
            logger.info(f"📡 Telegram API response: {result}")
            
            if result.get("ok"):
                logger.info(f"✅ Telegram webhook registered successfully")
                logger.info(f"📍 Webhook URL: {webhook_url}")
                return True, "Webhook registered successfully"
            else:
                error_msg = result.get("description", "Unknown error")
                logger.warning(f"⚠️ Telegram webhook registration failed: {error_msg}")
                logger.warning(f"📡 Telegram API error response: {result}")
                return False, f"Telegram API error: {error_msg}"
        else:
            # Try to parse error response
            try:
                error_response = response.json()
                logger.warning(f"⚠️ Telegram webhook registration failed with status {response.status_code}")
                logger.warning(f"📡 Telegram API error response: {error_response}")
                error_desc = error_response.get("description", f"HTTP {response.status_code}")
                return False, error_desc
            except:
                logger.warning(f"⚠️ Telegram webhook registration failed with status {response.status_code}")
                logger.warning(f"📡 Response text: {response.text}")
                return False, f"HTTP {response.status_code}"
    
    except requests.exceptions.Timeout:
        logger.error("❌ Telegram webhook registration timeout")
        return False, "Timeout"
    
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Telegram webhook registration error: {e}")
        return False, f"Request error: {e}"
    
    except Exception as e:
        logger.error(f"❌ Unexpected webhook registration error: {e}")
        return False, f"Unexpected error: {e}"


def verify_webhook_registration(bot_token: str) -> Tuple[bool, dict]:
    """
    Verify if webhook is registered.
    
    Args:
        bot_token: Telegram bot token
    
    Returns:
        Tuple of (is_registered, webhook_info)
    """
    try:
        if not bot_token:
            return False, {"error": "No token provided"}
        
        telegram_api_url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
        
        response = requests.get(telegram_api_url, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get("ok"):
                webhook_info = result.get("result", {})
                is_registered = bool(webhook_info.get("url"))
                
                if is_registered:
                    logger.info(f"✅ Webhook verified: {webhook_info.get('url')}")
                else:
                    logger.info("ℹ️ No webhook registered")
                
                return is_registered, webhook_info
            else:
                return False, {"error": result.get("description")}
        else:
            return False, {"error": f"HTTP {response.status_code}"}
    
    except Exception as e:
        logger.error(f"❌ Webhook verification error: {e}")
        return False, {"error": str(e)}


def delete_webhook(bot_token: str) -> Tuple[bool, str]:
    """
    Delete Telegram webhook.
    
    Args:
        bot_token: Telegram bot token
    
    Returns:
        Tuple of (success, message)
    """
    try:
        if not bot_token:
            return True, "Skipped (no token)"
        
        telegram_api_url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
        
        response = requests.get(telegram_api_url, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get("ok"):
                logger.info("✅ Telegram webhook deleted")
                return True, "Webhook deleted"
            else:
                return False, result.get("description", "Unknown error")
        else:
            return False, f"HTTP {response.status_code}"
    
    except Exception as e:
        logger.error(f"❌ Webhook deletion error: {e}")
        return False, f"Error: {e}"


def register_telegram_webhook_with_retry(
    bot_token: str,
    domain: str,
    project_id: int,
    max_retries: int = 9,
    initial_delay: int = 10
) -> Tuple[bool, str]:
    """
    Register Telegram webhook with automatic retries and exponential backoff.
    
    This function handles DNS propagation delays by retrying webhook registration
    with increasing intervals. Telegram's servers may not have propagated DNS yet,
    so we retry until it succeeds or max retries reached.
    
    Args:
        bot_token: Telegram bot token
        domain: Webhook domain (e.g., mybot.dreambigwithai.com)
        project_id: Project ID for webhook path
        max_retries: Maximum number of retry attempts (default: 9)
        initial_delay: Initial delay before first retry in seconds (default: 10)
    
    Returns:
        Tuple of (success, message)
    
    Retry Schedule (exponential backoff):
        - Retry 1: 10s delay
        - Retry 2: 20s delay
        - Retry 3: 40s delay
        - Retry 4: 80s delay
        - Retry 5: 160s delay
        - Retry 6: 320s delay
        - Retry 7: 640s delay
        - Retry 8: 1280s delay (~21 min)
        - Retry 9: 2560s delay (~43 min)
        Total max wait time: ~5110 seconds (85 minutes)
    """
    for attempt in range(max_retries):
        # Try registering webhook
        success, message = register_telegram_webhook(bot_token, domain, project_id)
        
        if success:
            logger.info(f"✅ Webhook registration succeeded on attempt {attempt + 1}/{max_retries}")
            return True, message
        
        # Check if error is DNS-related (retryable)
        if "Failed to resolve host" in message or "Name or service not known" in message:
            if attempt < max_retries - 1:
                # Calculate exponential backoff delay
                delay = initial_delay * (2 ** attempt)
                logger.warning(f"⚠️ DNS not propagated yet (attempt {attempt + 1}/{max_retries})")
                logger.info(f"⏳ Waiting {delay}s before retry...")
                time.sleep(delay)
            else:
                logger.error(f"❌ Webhook registration failed after {max_retries} attempts")
                logger.error(f"   DNS propagation took too long - webhook will need manual registration")
                return False, f"DNS propagation timeout after {max_retries} attempts"
        else:
            # Non-DNS error - don't retry
            logger.error(f"❌ Webhook registration failed with non-retryable error: {message}")
            return False, message
    
    return False, "Max retries exceeded"


def register_webhook_async(
    bot_token: str,
    domain: str,
    project_id: int,
    max_retries: int = 9,
    initial_delay: int = 10
) -> None:
    """
    Register Telegram webhook asynchronously in a background thread.
    
    This function starts webhook registration in a separate thread so the deployment
    pipeline can continue without waiting for DNS propagation. Webhook will be
    registered in the background with retries.
    
    Args:
        bot_token: Telegram bot token
        domain: Webhook domain (e.g., mybot.dreambigwithai.com)
        project_id: Project ID
        max_retries: Maximum retry attempts (default: 6)
        initial_delay: Initial delay in seconds (default: 10)
    
    Note:
        - Runs in background thread (non-blocking)
        - Logs progress independently
        - Errors are logged but don't affect deployment status
    """
    def _background_registration():
        logger.info(f"🔄 Starting async webhook registration for {domain}")
        
        try:
            success, message = register_telegram_webhook_with_retry(
                bot_token=bot_token,
                domain=domain,
                project_id=project_id,
                max_retries=max_retries,
                initial_delay=initial_delay
            )
            
            if success:
                logger.info(f"✅ Async webhook registration completed: {message}")
            else:
                logger.warning(f"⚠️ Async webhook registration failed: {message}")
                logger.info(f"ℹ️ To register manually: curl -X POST 'https://api.telegram.org/bot{bot_token}/setWebhook?url=https://{domain}/webhook'")
        
        except Exception as e:
            logger.error(f"❌ Async webhook registration error: {e}")
    
    # Start background thread
    thread = threading.Thread(target=_background_registration, daemon=True)
    thread.start()
    logger.info(f"🚀 Webhook registration running in background (will retry up to {max_retries} times)")

