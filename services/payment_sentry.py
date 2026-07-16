import os
from typing import Any, Dict, Optional

from services.sentry_config import capture_exception, capture_message


def _success_events_enabled() -> bool:
    value = os.getenv("PAYMENT_SENTRY_SUCCESS_EVENTS", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _clean_context(**kwargs: Any) -> Dict[str, Any]:
    """Keep payment Sentry context useful but intentionally non-sensitive."""
    allowed = {
        "provider",
        "event",
        "action",
        "user_id",
        "variant_id",
        "pack_id",
        "credits",
        "credit_type",
        "plan",
        "status_code",
        "reason",
        "handled",
        "checkout_id",
        "order_id",
        "subscription_id",
    }
    return {key: value for key, value in kwargs.items() if key in allowed and value not in (None, "")}


def capture_payment_success(
    *,
    event: str,
    action: str,
    provider: str = "lemonsqueezy",
    **context: Any,
) -> None:
    """Capture successful payment events only when explicitly enabled."""
    if not _success_events_enabled():
        return

    safe_context = _clean_context(provider=provider, event=event, action=action, handled=True, **context)
    capture_message(
        f"Payment event succeeded: {provider}.{event}.{action}",
        level="info",
        tags={"area": "billing", "provider": provider, "payment_event": event, "payment_action": action},
        context=safe_context,
    )


def capture_payment_failure(
    *,
    event: str,
    reason: str,
    provider: str = "lemonsqueezy",
    exc: Optional[BaseException] = None,
    **context: Any,
) -> None:
    """Capture payment failures/anomalies without raw payloads or secrets."""
    safe_context = _clean_context(
        provider=provider,
        event=event,
        reason=reason,
        handled=False,
        **context,
    )
    tags = {"area": "billing", "provider": provider, "payment_event": event}

    if exc is not None:
        capture_exception(exc, tags=tags, context=safe_context)
        return

    capture_message(
        f"Payment event failed: {provider}.{event} - {reason}",
        level="error",
        tags=tags,
        context=safe_context,
    )
