import logging
import os
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

_sentry_sdk = None
_enabled = False
_configured_service: Optional[str] = None

SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "dsn",
    "webhook",
    "bot_token",
    "access_key",
    "private_key",
)

SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+", re.IGNORECASE),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{25,}\b"),
    re.compile(r"https://[^@\s]+@[^/\s]+/[A-Za-z0-9]+"),
)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _logging_level(name: str, default: int) -> int:
    value = os.getenv(name, "").upper().strip()
    return getattr(logging, value, default) if value else default


def _is_sensitive_key(key: Any) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _redact_string(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[Filtered]", redacted)
    return redacted


def _scrub(value: Any, key: Any = None) -> Any:
    if _is_sensitive_key(key):
        return "[Filtered]"
    if isinstance(value, dict):
        return {item_key: _scrub(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub(item) for item in value)
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _before_send(event: Dict[str, Any], _hint: Dict[str, Any]) -> Dict[str, Any]:
    return _scrub(event)


def configure_sentry(service_name: str) -> bool:
    """Initialize Sentry once for the current process if SENTRY_DSN is present."""
    global _sentry_sdk, _enabled, _configured_service

    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        logger.info("[SENTRY] disabled for %s (SENTRY_DSN not set)", service_name)
        return False

    if _enabled:
        set_tag("service", _configured_service or service_name)
        return True

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        integrations = [
            LoggingIntegration(
                level=logging.INFO,
                event_level=_logging_level("SENTRY_LOG_LEVEL", logging.ERROR),
            )
        ]
        try:
            from sentry_sdk.integrations.fastapi import FastApiIntegration

            integrations.append(FastApiIntegration())
        except Exception:
            logger.debug("[SENTRY] FastAPI integration unavailable; continuing with default integrations")

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
            release=os.getenv("SENTRY_RELEASE") or None,
            traces_sample_rate=_env_float("SENTRY_TRACES_SAMPLE_RATE", 0.0),
            profiles_sample_rate=_env_float("SENTRY_PROFILES_SAMPLE_RATE", 0.0),
            send_default_pii=_env_bool("SENTRY_SEND_DEFAULT_PII", False),
            integrations=integrations,
            before_send=_before_send,
        )
        _sentry_sdk = sentry_sdk
        _enabled = True
        _configured_service = service_name
        set_tag("service", service_name)
        logger.info("[SENTRY] initialized for %s", service_name)
        return True
    except Exception as exc:
        logger.warning("[SENTRY] initialization failed for %s: %s", service_name, exc)
        _enabled = False
        return False


def is_enabled() -> bool:
    return bool(_enabled and _sentry_sdk)


def set_tag(key: str, value: Any) -> None:
    if not is_enabled():
        return
    try:
        _sentry_sdk.set_tag(key, str(value))
    except Exception:
        pass


def set_context(name: str, value: Dict[str, Any]) -> None:
    if not is_enabled():
        return
    try:
        _sentry_sdk.set_context(name, _scrub(value))
    except Exception:
        pass


@contextmanager
def scoped_context(
    *,
    tags: Optional[Dict[str, Any]] = None,
    contexts: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Iterator[None]:
    if not is_enabled():
        yield
        return

    with _sentry_sdk.push_scope() as scope:
        for key, value in (tags or {}).items():
            scope.set_tag(key, str(value))
        for name, value in (contexts or {}).items():
            scope.set_context(name, _scrub(value))
        yield


def capture_exception(
    exc: BaseException,
    *,
    tags: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    if not is_enabled():
        return
    with scoped_context(tags=tags, contexts={"context": context or {}}):
        _sentry_sdk.capture_exception(exc)


def capture_message(
    message: str,
    *,
    level: str = "error",
    tags: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    if not is_enabled():
        return
    with scoped_context(tags=tags, contexts={"context": context or {}}):
        _sentry_sdk.capture_message(message, level=level)
