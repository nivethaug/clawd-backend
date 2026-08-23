"""
Integration Catalog — first-class definitions for managed integrations.

Phase 1: API-key integrations only (no OAuth). Each definition declares
the env key(s) it materializes into a project .env, plus a server-side
validator that checks the credential WITHOUT ever logging or echoing it.

Multiple credentials of the same app are supported at the vault level
(distinct key names, e.g. OPENAI_API_KEY + OPENAI_API_KEY_2 — the same
_TELEGRAM_BOT_TOKEN_2 pattern Global Integrations already documents).
Within ONE project, two credentials may coexist only when their key
names differ; a same-key-name connect requires an explicit swap.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("integrations.catalog")

TIMEOUT = 10.0


@dataclass(frozen=True)
class IntegrationDef:
    type: str                    # catalog id, e.g. 'openai'
    title: str                   # display name
    category: str                # matches env registry categories
    key_names: List[str]         # env keys materialized (in connect order)
    docs_url: str
    description: str
    validator: str               # name of the validator function
    icon_hint: str = "key"       # frontend picks an icon per type
    multi_key: bool = False      # True => ALL key_names required to connect


def _hdr_bearer(key: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def _v_openai(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get("https://api.openai.com/v1/models", headers=_hdr_bearer(values["OPENAI_API_KEY"]))
    return (r.status_code == 200), (await _org_from(r) if r.status_code == 200 else None)


async def _v_openrouter(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get("https://openrouter.ai/api/v1/key", headers=_hdr_bearer(values["OPENROUTER_API_KEY"]))
    ok = r.status_code == 200
    info = None
    if ok:
        try:
            d = r.json().get("data", {})
            info = d.get("label") or "key valid"
        except Exception:
            info = "key valid"
    return ok, info


async def _v_anthropic(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": values["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        },
    )
    return (r.status_code == 200), ("key valid" if r.status_code == 200 else None)


async def _v_gemini(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get(
        f"https://generativelanguage.googleapis.com/v1/models?key={values['GEMINI_API_KEY']}"
    )
    return (r.status_code == 200), ("key valid" if r.status_code == 200 else None)


async def _v_github(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {values['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json"},
    )
    ok = r.status_code == 200
    info = None
    if ok:
        try:
            info = r.json().get("login")
        except Exception:
            pass
    return ok, info


async def _v_telegram_bot(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get(f"https://api.telegram.org/bot{values['TELEGRAM_BOT_TOKEN']}/getMe")
    ok = r.status_code == 200
    info = None
    if ok:
        try:
            result = r.json().get("result", {})
            info = f"@{result.get('username', 'bot')}"
        except Exception:
            pass
    return ok, info


async def _v_discord_bot(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get("https://discord.com/api/users/@me",
                   headers={"Authorization": f"Bot {values['DISCORD_TOKEN']}"})
    ok = r.status_code == 200
    info = None
    if ok:
        try:
            info = r.json().get("username")
        except Exception:
            pass
    return ok, info


async def _v_stripe(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get("https://api.stripe.com/v1/balance",
                   headers=_hdr_bearer(values["STRIPE_SECRET_KEY"]))
    return (r.status_code == 200), ("key valid" if r.status_code == 200 else None)


async def _v_razorpay(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get(
        "https://api.razorpay.com/v1/payments?count=1",
        auth=(values["RAZORPAY_KEY_ID"], values["RAZORPAY_KEY_SECRET"]),
    )
    return (r.status_code == 200), ("keys valid" if r.status_code == 200 else None)


async def _v_resend(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get("https://api.resend.com/domains", headers=_hdr_bearer(values["RESEND_API_KEY"]))
    return (r.status_code == 200), ("key valid" if r.status_code == 200 else None)


async def _v_slack_webhook(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    url = values["SLACK_WEBHOOK_URL"]
    if not url.startswith("https://hooks.slack.com/"):
        return False, "not a Slack webhook URL"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(url, json={"text": "✅ DreamAgent integration verified"})
    return (r.status_code == 200), ("webhook valid" if r.status_code == 200 else None)


async def _v_coingecko(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    r = await _get(
        "https://api.coingecko.com/api/v3/ping",
        headers={"x-cg-demo-api-key": values["COINGECKO_API_KEY"]},
    )
    return (r.status_code == 200), ("key valid" if r.status_code == 200 else None)


async def _v_serper(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            "https://google.serper.dev/account",
            headers={"X-API-KEY": values["SERPER_API_KEY"], "Content-Type": "application/json"},
        )
    ok = r.status_code == 200
    info = None
    if ok:
        try:
            info = f"credits: {r.json().get('credits')}"
        except Exception:
            info = "key valid"
    return ok, info


async def _get(url: str, headers: Dict[str, str] = None, auth=None) -> "httpx.Response":
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        return await client.get(url, headers=headers, auth=auth)


async def _org_from(r: "httpx.Response") -> Optional[str]:
    return "key valid"  # keep response body out of logs


async def _v_youtube(values: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    # Cheapest quota-wise call (1 unit) that still proves the key works.
    r = await _get(
        "https://www.googleapis.com/youtube/v3/videoCategories"
        "?part=snippet&regionCode=US"
        f"&key={values['YOUTUBE_API_KEY']}"
    )
    return (r.status_code == 200), ("key valid (public data)" if r.status_code == 200 else None)


_VALIDATORS = {
    "openai": _v_openai,
    "openrouter": _v_openrouter,
    "anthropic": _v_anthropic,
    "gemini": _v_gemini,
    "github": _v_github,
    "telegram-bot": _v_telegram_bot,
    "discord-bot": _v_discord_bot,
    "stripe": _v_stripe,
    "razorpay": _v_razorpay,
    "resend": _v_resend,
    "slack_webhook": _v_slack_webhook,
    "coingecko": _v_coingecko,
    "serper": _v_serper,
    "youtube": _v_youtube,
}

CATALOG: Dict[str, IntegrationDef] = {
    d.type: d
    for d in [
        IntegrationDef(
            type="openai", title="OpenAI", category="AI",
            key_names=["OPENAI_API_KEY"],
            docs_url="https://platform.openai.com/api-keys",
            description="GPT models for chat, images and embeddings.",
            validator="openai", icon_hint="openai",
        ),
        IntegrationDef(
            type="openrouter", title="OpenRouter", category="AI",
            key_names=["OPENROUTER_API_KEY"],
            docs_url="https://openrouter.ai/keys",
            description="One key, hundreds of models (GPT, Claude, Gemini, Llama).",
            validator="openrouter", icon_hint="openrouter",
        ),
        IntegrationDef(
            type="anthropic", title="Anthropic", category="AI",
            key_names=["ANTHROPIC_API_KEY"],
            docs_url="https://console.anthropic.com/settings/keys",
            description="Claude models.",
            validator="anthropic", icon_hint="anthropic",
        ),
        IntegrationDef(
            type="gemini", title="Google Gemini", category="AI",
            key_names=["GEMINI_API_KEY"],
            docs_url="https://aistudio.google.com/app/apikey",
            description="Gemini models from Google AI Studio.",
            validator="gemini", icon_hint="gemini",
        ),
        IntegrationDef(
            type="github", title="GitHub", category="Integrations",
            key_names=["GITHUB_TOKEN"],
            docs_url="https://github.com/settings/tokens",
            description="Repo access, commits and automation (fine-grained or classic PAT).",
            validator="github", icon_hint="github",
        ),
        IntegrationDef(
            type="telegram-bot", title="Telegram Bot", category="Bots",
            key_names=["TELEGRAM_BOT_TOKEN"],
            docs_url="https://t.me/BotFather",
            description="Telegram bot token from @BotFather — for building bots and sending messages.",
            validator="telegram-bot", icon_hint="telegram",
        ),
        IntegrationDef(
            type="discord-bot", title="Discord Bot", category="Bots",
            key_names=["DISCORD_TOKEN"],
            docs_url="https://discord.com/developers/applications",
            description="Discord bot token from the Developer Portal — for building bots.",
            validator="discord-bot", icon_hint="discord",
        ),
        IntegrationDef(
            type="stripe", title="Stripe", category="Payments",
            key_names=["STRIPE_SECRET_KEY"],
            docs_url="https://dashboard.stripe.com/apikeys",
            description="Payments, subscriptions and payouts.",
            validator="stripe", icon_hint="stripe",
        ),
        IntegrationDef(
            type="razorpay", title="Razorpay", category="Payments",
            key_names=["RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"],
            docs_url="https://dashboard.razorpay.com/app/keys",
            description="Indian payments (INR). Stores BOTH key id and secret.",
            validator="razorpay", icon_hint="razorpay", multi_key=True,
        ),
        IntegrationDef(
            type="resend", title="Resend", category="Email",
            key_names=["RESEND_API_KEY"],
            docs_url="https://resend.com/api-keys",
            description="Transactional email API.",
            validator="resend", icon_hint="resend",
        ),
        IntegrationDef(
            type="slack_webhook", title="Slack Webhook", category="Bots",
            key_names=["SLACK_WEBHOOK_URL"],
            docs_url="https://api.slack.com/messaging/webhooks",
            description="Post messages to a Slack channel via incoming webhook.",
            validator="slack_webhook", icon_hint="slack",
        ),
        IntegrationDef(
            type="coingecko", title="CoinGecko", category="Integrations",
            key_names=["COINGECKO_API_KEY"],
            docs_url="https://www.coingecko.com/en/api",
            description="Crypto prices and market data (demo key).",
            validator="coingecko", icon_hint="coingecko",
        ),
        IntegrationDef(
            type="serper", title="Serper", category="Integrations",
            key_names=["SERPER_API_KEY"],
            docs_url="https://serper.dev/api-key",
            description="Google search API for news and web results.",
            validator="serper", icon_hint="serper",
        ),
        IntegrationDef(
            type="youtube", title="YouTube", category="Integrations",
            key_names=["YOUTUBE_API_KEY"],
            docs_url="https://console.cloud.google.com/apis/credentials",
            description="YouTube Data API — search, videos and channel stats (public data).",
            validator="youtube", icon_hint="youtube",
        ),
    ]
}


def get_def(integration_type: str) -> Optional[IntegrationDef]:
    return CATALOG.get(integration_type)


def catalog_metadata() -> List[Dict[str, Any]]:
    """Public catalog for the frontend (no secrets, no validator internals)."""
    return [
        {
            "type": d.type, "title": d.title, "category": d.category,
            "key_names": list(d.key_names), "docs_url": d.docs_url,
            "description": d.description, "icon_hint": d.icon_hint,
            "multi_key": d.multi_key,
        }
        for d in CATALOG.values()
    ]


async def validate_credentials(integration_type: str, values: Dict[str, str]) -> Dict[str, Any]:
    """Run the server-side validator for a catalog type.

    values must contain every key_name for the definition. Never logs or
    returns the credential itself — only valid/invalid + a short info line.
    """
    d = get_def(integration_type)
    if not d:
        return {"valid": False, "error": "unknown integration type"}
    missing = [k for k in d.key_names if not (values or {}).get(k)]
    if missing:
        return {"valid": False, "error": f"missing: {', '.join(missing)}"}
    fn = _VALIDATORS[d.validator]
    try:
        ok, info = await fn(values)
    except Exception as e:
        # Log the exception TYPE only — never headers/bodies that carry keys.
        logger.warning("[INTEGRATIONS] validator %s raised %s", d.validator, type(e).__name__)
        return {"valid": False, "error": "validation request failed"}
    if ok:
        return {"valid": True, "info": info}
    return {"valid": False, "error": "credential rejected by provider"}
