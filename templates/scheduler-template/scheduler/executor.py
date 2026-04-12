#!/usr/bin/env python3
"""
Executor - Default project executor for scheduled jobs.

This file is the DEFAULT executor deployed with the scheduler template.
AI agents modify this file to add project-specific logic.

Supports DYNAMIC CONTENT via the `fetch` field in payload.
Before sending, the executor fetches live data and injects it into templates.

AI agents can:
1. Add new fetch_data_* functions below
2. Add new task_type handlers
3. Add new template variables to FETCH_DATA_REGISTRY

Required interface:
    execute_task(job: dict) -> dict

    Args:
        job: {"id": int, "task_type": str, "payload": dict, ...}

    Returns:
        {"status": "success"|"failed", "message": str}
"""

import json
import logging
import smtplib
from typing import Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    DISCORD_WEBHOOK_URL,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, EMAIL_TO,
    API_ENDPOINT,
)
from services import api_client

logger = logging.getLogger('scheduler.executor')


# ============================================================================
# Dynamic Content Resolution
# ============================================================================

# Registry: variable name -> function that returns a value
# AI agents add new entries here to support new data sources
FETCH_DATA_REGISTRY = {
    "btc_price": lambda: _fetch_crypto("bitcoin"),
    "eth_price": lambda: _fetch_crypto("ethereum"),
    "weather": lambda: _fetch_weather(),
    "news": lambda: _fetch_news(),
}


def _fetch_crypto(coin: str) -> str:
    """Fetch crypto price, returns formatted string."""
    result = api_client.get_crypto_price(coin)
    if result.get("success"):
        return f"${result['price']:,.2f}"
    return f"unavailable ({result.get('error', 'unknown')})"


def _fetch_weather() -> str:
    """Fetch weather data, returns formatted string."""
    result = api_client.get_weather()
    if result.get("success"):
        return f"{result['temperature']}C, wind {result['windspeed']}km/h"
    return f"unavailable ({result.get('error', 'unknown')})"


def _fetch_news() -> str:
    """Fetch top news, returns formatted string."""
    result = api_client.get_news()
    if result.get("success"):
        return " | ".join(result.get("stories", [])[:3])
    return f"unavailable ({result.get('error', 'unknown')})"


def resolve_content(payload: dict) -> dict:
    """
    Resolve dynamic content in payload before execution.

    The payload can have a `fetch` field listing data sources to resolve:
    {
        "fetch": ["btc_price"],
        "text": "BTC: {{btc_price}}"
    }

    This replaces {{btc_price}} with live data before sending.

    Args:
        payload: Original payload dict

    Returns:
        Payload with dynamic content resolved
    """
    fetch_keys = payload.get("fetch", [])
    if not fetch_keys:
        return payload

    # Fetch all requested data
    resolved = {}
    for key in fetch_keys:
        fetcher = FETCH_DATA_REGISTRY.get(key)
        if fetcher:
            try:
                resolved[key] = fetcher()
                logger.info(f"Resolved {key}: {resolved[key][:50]}")
            except Exception as e:
                logger.error(f"Failed to resolve {key}: {e}")
                resolved[key] = f"error: {e}"
        else:
            logger.warning(f"Unknown fetch key: {key}")
            resolved[key] = f"unknown: {key}"

    # Replace {{key}} in all string fields
    payload = _deep_replace(payload, resolved)
    return payload


def _deep_replace(obj, resolved: dict):
    """Recursively replace {{key}} in all string values."""
    if isinstance(obj, str):
        for key, value in resolved.items():
            obj = obj.replace("{{" + key + "}}", str(value))
        return obj
    elif isinstance(obj, dict):
        return {k: _deep_replace(v, resolved) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_deep_replace(v, resolved) for v in obj]
    return obj


# ============================================================================
# Task Execution Router
# ============================================================================

def execute_task(job: dict) -> dict:
    """
    Execute a scheduled job.

    Steps:
    1. Extract task_type and payload from job
    2. Resolve dynamic content ({{btc_price}} etc.)
    3. Route to the appropriate handler
    4. Return structured result

    Args:
        job: Full job dict with keys: id, task_type, payload, job_type, etc.

    Returns:
        {"status": "success"|"failed", "message": str}
    """
    task_type = job.get("task_type", "")
    payload = job.get("payload", {})

    # Parse payload if JSONB string
    if isinstance(payload, str):
        try:
            import json
            payload = json.loads(payload)
        except Exception:
            payload = {}

    try:
        # Step 1: Resolve dynamic content
        payload = resolve_content(payload)

        # Step 2: Route to handler
        if task_type == 'telegram':
            status, message = _send_telegram(payload)
        elif task_type == 'discord':
            status, message = _send_discord(payload)
        elif task_type == 'email':
            status, message = _send_email(payload)
        elif task_type == 'api':
            status, message = _call_api(payload)
        elif task_type == 'trade':
            status, message = _execute_trade(payload)
        else:
            status, message = 'failed', f'Unknown task_type: {task_type}'

        return {"status": status, "message": message}

    except Exception as e:
        logger.error(f"Task execution error ({task_type}): {e}")
        return {"status": "failed", "message": str(e)}


# ============================================================================
# Task Handlers
# ============================================================================

def _send_telegram(payload: dict) -> Tuple[str, str]:
    """Send a message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        return ('failed', 'TELEGRAM_BOT_TOKEN not configured')

    chat_id = payload.get('chat_id', TELEGRAM_CHAT_ID)
    text = payload.get('text', '')

    if not chat_id:
        return ('failed', 'Missing chat_id in payload')

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(url, json={
        'chat_id': chat_id,
        'text': text
    }, timeout=10)
    response.raise_for_status()

    return ('success', f'Message sent to {chat_id}')


def _send_discord(payload: dict) -> Tuple[str, str]:
    """Send a message via Discord webhook."""
    webhook_url = payload.get('webhook_url', DISCORD_WEBHOOK_URL)
    content = payload.get('content', payload.get('text', ''))

    if not webhook_url:
        return ('failed', 'Missing webhook_url in payload')

    response = requests.post(webhook_url, json={
        'content': content
    }, timeout=10)
    response.raise_for_status()

    return ('success', 'Discord message sent')


def _send_email(payload: dict) -> Tuple[str, str]:
    """Send an email via SMTP (supports plain text and HTML)."""
    if not SMTP_HOST or not SMTP_USER:
        return ('failed', 'SMTP not configured')

    from_addr = SMTP_FROM or SMTP_USER
    to_addr = payload.get('to', EMAIL_TO)
    subject = payload.get('subject', 'Scheduler Notification')
    body = payload.get('body', payload.get('text', ''))
    html = payload.get('html', '')

    if not to_addr:
        return ('failed', 'Missing "to" address in payload')

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        if SMTP_PASS:
            server.login(SMTP_USER, SMTP_PASS)

        if html:
            # HTML email
            msg = MIMEMultipart()
            msg['From'] = from_addr
            msg['To'] = to_addr
            msg['Subject'] = subject
            msg.attach(MIMEText(html, 'html'))
        else:
            # Plain text email
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = from_addr
            msg['To'] = to_addr

        server.sendmail(from_addr, to_addr, msg.as_string())

    return ('success', f'Email sent to {to_addr}')


def _call_api(payload: dict) -> Tuple[str, str]:
    """Call an external API endpoint."""
    url = payload.get('url', API_ENDPOINT)
    if not url:
        return ('failed', 'Missing url in payload')

    method = payload.get('method', 'GET').upper()
    headers = payload.get('headers', {})
    body = payload.get('body')
    timeout = payload.get('timeout', 10)

    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        json=body if body else None,
        timeout=timeout
    )

    status = 'success' if response.status_code < 400 else 'failed'
    return (status, f'{method} {url} -> {response.status_code}')


def _execute_trade(payload: dict) -> Tuple[str, str]:
    """Execute a paper trade (safe placeholder)."""
    action = payload.get('action', 'buy')
    symbol = payload.get('symbol', 'BTC')
    amount = payload.get('amount', 0)

    logger.info(f"Paper trade: {action} {amount} {symbol}")

    return ('success', f'Paper trade: {action} {amount} {symbol}')
