import logging
import os
from typing import Any, Dict, Optional

from services.sentry_config import capture_exception, capture_message, is_enabled

logger = logging.getLogger("payment.audit")

# Payment outcomes are an audit trail: success AND failure must always be
# recorded. They are emitted to PM2 logs unconditionally, and forwarded to
# Sentry whenever Sentry is configured.


def _clean_context(**kwargs: Any) -> Dict[str, Any]:
    """Keep payment audit context useful but intentionally non-sensitive."""
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


def _sentry_on() -> bool:
    return is_enabled()


def _fmt_audit(kind: str, provider: str, event: str, detail: str, ctx: Dict[str, Any]) -> str:
    """Single structured line for PM2 logs (grep-able: 'PAYMENT_AUDIT')."""
    # Drop fields already shown as top-level keys to avoid duplication.
    deduped = {k: v for k, v in ctx.items() if k not in {"provider", "event"}}
    ctx_str = " ".join(f"{k}={v}" for k, v in sorted(deduped.items()))
    sentry_state = "sentry=on" if _sentry_on() else "sentry=off"
    return (
        f"PAYMENT_AUDIT kind={kind} provider={provider} event={event} "
        f"{sentry_state} detail={detail} {ctx_str}".rstrip()
    )


def capture_payment_success(
    *,
    event: str,
    action: str,
    provider: str = "lemonsqueezy",
    **context: Any,
) -> None:
    """Audit a successful payment event.

    Always logged to PM2 logs. Forwarded to Sentry when configured. (Success
    capture is unconditional — payment outcomes are a mandatory audit trail.)
    """
    safe_ctx = _clean_context(provider=provider, event=event, action=action, handled=True, **context)

    logger.info(
        _fmt_audit("success", provider, event, action, safe_ctx)
    )

    if _sentry_on():
        capture_message(
            f"Payment event succeeded: {provider}.{event}.{action}",
            level="info",
            tags={"area": "billing", "provider": provider, "payment_event": event, "payment_action": action},
            context=safe_ctx,
        )


def capture_payment_failure(
    *,
    event: str,
    reason: str,
    provider: str = "lemonsqueezy",
    exc: Optional[BaseException] = None,
    **context: Any,
) -> None:
    """Audit a failed/anomalous payment event.

    Always logged to PM2 logs (warning). Forwarded to Sentry when configured.
    """
    safe_ctx = _clean_context(
        provider=provider,
        event=event,
        reason=reason,
        handled=False,
        **context,
    )

    logger.warning(
        _fmt_audit("failure", provider, event or "unknown", reason, safe_ctx)
    )

    if _sentry_on():
        tags = {"area": "billing", "provider": provider, "payment_event": event}
        if exc is not None:
            capture_exception(exc, tags=tags, context=safe_ctx)
        else:
            capture_message(
                f"Payment event failed: {provider}.{event} - {reason}",
                level="error",
                tags=tags,
                context=safe_ctx,
            )
