#!/usr/bin/env python3
"""
Validate Router - Pre-validation endpoint for project credentials.

Verifies Telegram bot tokens, Discord bot tokens, and scheduler
sender channels (Telegram, Discord, Email, API) before project creation.

Usage:
    POST /api/validate/credentials
    {
        "type_id": 2,
        "bot_token": "123456:ABC..."
    }

    POST /api/validate/credentials
    {
        "type_id": 5,
        "telegram_bot_token": "123456:ABC...",
        "email_to": "user@email.com"
    }
"""

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse
from pydantic import BaseModel
from fastapi import APIRouter, Header, HTTPException

import logging
from utils.logger import logger  # noqa: F811 — reassign below
from utils.auth_helpers import get_user_id_from_token
logger = logging.getLogger("api.validate_router")

router = APIRouter()


class ValidateCredentialsRequest(BaseModel):
    type_id: int
    # Telegram bot (type_id=2) or Discord bot (type_id=3)
    bot_token: Optional[str] = None
    # Scheduler channels (type_id=5)
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    discord_webhook_url: Optional[str] = None
    email_to: Optional[str] = None
    api_endpoint: Optional[str] = None


@router.post("/credentials")
async def validate_credentials(request: ValidateCredentialsRequest, authorization: Optional[str] = Header(None)):
    """
    Validate credentials for a project type before creation.

    type_id=1 (Website): No validation needed, returns valid immediately.
    type_id=2 (Telegram bot): Validates bot_token via Telegram getMe.
    type_id=3 (Discord bot): Validates bot_token via Discord users/@me.
    type_id=5 (Scheduler): Validates each provided sender channel.

    Requires authentication — prevents unauthenticated SSRF via the
    discord_webhook_url and api_endpoint fields.
    """
    # Auth check — this endpoint makes outbound requests to user-supplied URLs
    user_id = get_user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    type_id = request.type_id

    # SSRF protection: validate user-supplied URLs before passing to validators
    if request.discord_webhook_url:
        _validate_safe_url(request.discord_webhook_url)
    if request.api_endpoint:
        _validate_safe_url(request.api_endpoint)

    # Website - no credentials to validate
    if type_id == 1:
        return {"valid": True, "type_id": type_id, "channels": {}}

    # Telegram bot
    if type_id == 2:
        if not request.bot_token:
            return {"valid": False, "type_id": type_id, "error": "bot_token is required for Telegram bot projects"}

        try:
            from services.telegram.validator import validate_telegram_token
            is_valid, info = validate_telegram_token(request.bot_token)

            if is_valid:
                logger.info(f"✅ Telegram bot token validated: @{info.get('username')}")
                return {
                    "valid": True,
                    "type_id": type_id,
                    "channels": {
                        "telegram": {
                            "valid": True,
                            "bot_id": info.get("bot_id"),
                            "bot_username": info.get("username"),
                            "first_name": info.get("first_name"),
                        }
                    }
                }
            else:
                logger.warning(f"❌ Telegram bot token invalid: {info.get('error')}")
                return {
                    "valid": False,
                    "type_id": type_id,
                    "error": info.get("error", "Invalid token"),
                    "channels": {
                        "telegram": {"valid": False, "error": info.get("error")}
                    }
                }
        except Exception as e:
            logger.error(f"Telegram validation error: {e}")
            return {"valid": False, "type_id": type_id, "error": str(e)}

    # Discord bot
    if type_id == 3:
        if not request.bot_token:
            return {"valid": False, "type_id": type_id, "error": "bot_token is required for Discord bot projects"}

        try:
            from services.discord.validator import validate_discord_token
            is_valid, info = validate_discord_token(request.bot_token)

            if is_valid:
                logger.info(f"✅ Discord bot token validated: {info.get('username')}")
                return {
                    "valid": True,
                    "type_id": type_id,
                    "channels": {
                        "discord": {
                            "valid": True,
                            "bot_id": info.get("bot_id"),
                            "username": info.get("username"),
                            "invite_url": info.get("invite_url"),
                        }
                    }
                }
            else:
                logger.warning(f"❌ Discord bot token invalid: {info.get('error')}")
                return {
                    "valid": False,
                    "type_id": type_id,
                    "error": info.get("error", "Invalid token"),
                    "channels": {
                        "discord": {"valid": False, "error": info.get("error")}
                    }
                }
        except Exception as e:
            logger.error(f"Discord validation error: {e}")
            return {"valid": False, "type_id": type_id, "error": str(e)}

    # Scheduler
    if type_id == 5:
        # At least one channel must be provided
        has_any = any([
            request.telegram_bot_token,
            request.discord_webhook_url,
            request.email_to,
            request.api_endpoint,
        ])
        if not has_any:
            return {
                "valid": False,
                "type_id": type_id,
                "error": "At least one sender channel is required for Scheduler projects"
            }

        try:
            from services.scheduler.validator import validate_scheduler_channels
            result = validate_scheduler_channels(
                telegram_bot_token=request.telegram_bot_token,
                telegram_chat_id=request.telegram_chat_id,
                discord_webhook_url=request.discord_webhook_url,
                email_to=request.email_to,
                api_endpoint=request.api_endpoint,
            )

            result["type_id"] = type_id
            if result["valid"]:
                logger.info(f"✅ Scheduler channels validated")
            else:
                logger.warning(f"❌ Scheduler channel validation failed")
            return result
        except Exception as e:
            logger.error(f"Scheduler validation error: {e}")
            return {"valid": False, "type_id": type_id, "error": str(e)}

    # Unknown type
    return {"valid": False, "type_id": type_id, "error": f"Unknown type_id: {type_id}"}


# ============================================================================
# API Endpoint Test - Same payload format as scheduler executor _call_api
# ============================================================================

class TestApiCallRequest(BaseModel):
    """Same format as scheduler executor's _call_api payload."""
    url: str
    method: str = "POST"
    headers: Optional[dict] = None
    body: Optional[dict] = None
    timeout: int = 10


BLOCKED_HEADER_NAMES = {
    "authorization",
    "cookie",
    "host",
    "x-forwarded-for",
    "x-real-ip",
    "x-forwarded-host",
    "x-forwarded-proto",
    "connection",
    "content-length",
}


def _is_blocked_ip(ip_address: str) -> bool:
    parsed = ipaddress.ip_address(ip_address)
    return any([
        parsed.is_private,
        parsed.is_loopback,
        parsed.is_link_local,
        parsed.is_multicast,
        parsed.is_reserved,
        parsed.is_unspecified,
    ])


def _validate_safe_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Only http and https URLs are allowed")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="URL must include a hostname")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Credentials in URLs are not allowed")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        resolved = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="Unable to resolve target host")

    blocked_ips = sorted({
        addr[4][0]
        for addr in resolved
        if _is_blocked_ip(addr[4][0])
    })
    if blocked_ips:
        logger.warning(
            "Blocked unsafe API validation target host=%s ips=%s",
            parsed.hostname,
            blocked_ips,
        )
        raise HTTPException(
            status_code=400,
            detail="Private, local, reserved, or link-local targets are not allowed",
        )

    return url


def _sanitize_headers(headers: Optional[dict]) -> dict:
    safe_headers = {}
    for key, value in (headers or {}).items():
        header_name = str(key).strip()
        header_key = header_name.lower()
        if not header_name:
            continue
        if header_key in BLOCKED_HEADER_NAMES or header_key.startswith("proxy-"):
            continue
        safe_headers[header_name] = str(value)
    return safe_headers


@router.post("/api-call")
async def test_api_call(
    request: TestApiCallRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Test an API endpoint using the same payload format as scheduler executor.

    This lets users verify their API endpoint works before creating
    scheduler jobs that call it.

    Payload matches scheduler executor's _call_api:
        url:     Target URL (required)
        method:  HTTP method (default: POST)
        headers: Optional request headers
        body:    Optional JSON body
        timeout: Request timeout in seconds (default: 10)

    Response:
        valid:   True if status < 400
        status:  HTTP status code
        method:  HTTP method used
        url:     Target URL
        body:    Response body (truncated to 2000 chars)
        error:   Error message if request failed
    """
    import requests as http

    try:
        get_user_id_from_token(authorization)
        method = request.method.upper()
        if method not in {"GET", "POST"}:
            raise HTTPException(status_code=400, detail="Only GET and POST methods are allowed")

        safe_url = _validate_safe_url(request.url)
        safe_headers = _sanitize_headers(request.headers)
        timeout = max(1, min(int(request.timeout or 10), 15))

        response = http.request(
            method=method,
            url=safe_url,
            headers=safe_headers,
            json=request.body if request.body else None,
            timeout=timeout,
            allow_redirects=False,
        )

        is_valid = response.status_code < 400

        # Try to parse response body
        try:
            resp_body = response.json()
        except Exception:
            resp_body = response.text[:2000] if response.text else None

        result = {
            "valid": is_valid,
            "status": response.status_code,
            "method": method,
            "url": safe_url,
        }

        if resp_body is not None:
            # Truncate large responses
            body_str = str(resp_body)
            if len(body_str) > 2000:
                body_str = body_str[:2000] + "... (truncated)"
            result["response"] = body_str

        logger.info("API call test: method=%s host=%s status=%s", method, urlparse(safe_url).hostname, response.status_code)
        return result

    except http.exceptions.Timeout:
        return {"valid": False, "error": "Request timed out", "url": request.url}
    except http.exceptions.ConnectionError:
        return {"valid": False, "error": "Connection failed", "url": request.url}
    except HTTPException:
        raise
    except Exception as e:
        return {"valid": False, "error": str(e), "url": request.url}
