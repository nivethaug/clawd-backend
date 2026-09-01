"""
OpenRouter API Client

Reusable chat completions client for OpenRouter-backed LLM calls.
Used by DreamAgent Prompt Assistant while keeping shared GLM clients untouched.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
PROMPT_ASSISTANT_MODEL = os.getenv("PROMPT_ASSISTANT_MODEL", "z-ai/glm-5.3-flash")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "DreamAgent")
# 45s per-request timeout — GLM-4.7-flash routinely takes 10-15s for the
# Prompt Assistant's large system prompt. 45s gives headroom for slow
# responses while staying under nginx's 60s proxy_read_timeout (which returns
# a CORS-blocking 504 if exceeded). With 1 retry, worst case is ~90s — the
# frontend client timeout is 120s.
DEFAULT_TIMEOUT = 45.0
MAX_RETRIES = 1
BACKOFF_SECONDS = 1.0
RETRYABLE_STATUSES = {408, 409, 429, 500, 502, 503, 504}


class OpenRouterClient:
    """
    Direct OpenRouter Chat Completions client.

    Uses the OpenRouter OpenAI-compatible API with Bearer token authentication.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        """
        Initialize OpenRouter client.

        Args:
            api_key: OpenRouter API key (defaults to OPENROUTER_API_KEY env var)
            model: Model name (defaults to PROMPT_ASSISTANT_MODEL env var)
        """
        self.api_key = api_key or OPENROUTER_API_KEY
        self.model = model or PROMPT_ASSISTANT_MODEL
        self.api_base = OPENROUTER_BASE_URL.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            logger.warning("[OPENROUTER-CLIENT] OPENROUTER_API_KEY not configured - API calls will fail")

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if OPENROUTER_SITE_URL:
            headers["HTTP-Referer"] = OPENROUTER_SITE_URL
        if OPENROUTER_APP_NAME:
            headers["X-Title"] = OPENROUTER_APP_NAME
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client

    def _build_payload(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        # Reasoning/thinking control — model dependent:
        # - Most GLM models: disable it (they burn 500-1500 reasoning tokens,
        #   25s-2.5min, before content; Prompt Assistant needs formatted text).
        # - glm-5.3-flash: thinking CANNOT be disabled — requesting
        #   {"enabled": false} makes the provider reject the call with 400
        #   (empty-body error passthrough, observed live on the stream path).
        #   Use effort=low instead: near-zero reasoning tokens, validated
        #   against the z.ai API.
        if "glm-5.3-flash" in (self.model or "").lower():
            payload["reasoning"] = {"effort": "low"}
        else:
            payload["reasoning"] = {"enabled": False}

        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        return payload

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: int = 1000,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        max_retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Call OpenRouter Chat Completions API.

        Args:
            messages: Conversation messages (system, user, assistant)
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response

        Returns:
            OpenRouter API response

        Raises:
            ValueError: If API key is not configured
            httpx.HTTPError: If API call fails
        """
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not configured")

        payload = self._build_payload(
            messages,
            temperature,
            max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        attempts = max(1, int(max_retries if max_retries is not None else MAX_RETRIES))
        logger.debug(
            "[OPENROUTER-CLIENT] Calling OpenRouter with %s messages, model=%s, tools=%s, attempts=%s",
            len(messages),
            self.model,
            len(tools or []),
            attempts,
        )

        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                client = await self._get_client()
                response = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                latency_ms = int((time.perf_counter() - started) * 1000)
                usage = data.get("usage", {})

                logger.info(
                    "[OPENROUTER-CLIENT] Response received in %sms (model=%s, tokens=%s)",
                    latency_ms,
                    data.get("model", self.model),
                    usage,
                )
                logger.debug(f"[OPENROUTER-CLIENT] Full response: {json.dumps(data, indent=2)}")
                return data

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning("[OPENROUTER-CLIENT] Timeout on attempt %s/%s", attempt, attempts)

            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code
                body = e.response.text

                if status_code in {401, 403}:
                    logger.error("[OPENROUTER-CLIENT] Invalid or unauthorized API key: HTTP %s", status_code)
                    raise

                if status_code == 429:
                    logger.warning("[OPENROUTER-CLIENT] Rate limited on attempt %s/%s: %s", attempt, attempts, body)
                elif status_code in RETRYABLE_STATUSES:
                    logger.warning(
                        "[OPENROUTER-CLIENT] Retryable provider error HTTP %s on attempt %s/%s: %s",
                        status_code,
                        attempt,
                        attempts,
                        body,
                    )
                else:
                    logger.error("[OPENROUTER-CLIENT] HTTP error %s: %s", status_code, body)
                    raise

            except Exception as e:
                logger.error(f"[OPENROUTER-CLIENT] Unexpected error: {e}")
                raise

            if attempt < attempts:
                backoff = BACKOFF_SECONDS * (2 ** (attempt - 1))
                await asyncio.sleep(backoff)

        if last_error:
            raise last_error
        raise RuntimeError("OpenRouter request failed")

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: int = 1000,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream OpenRouter Chat Completions chunks as parsed SSE JSON objects.

        Uses a dedicated httpx client (not the shared singleton) so the
        streaming connection is isolated from other requests and won't be
        closed mid-stream by a concurrent gate/vision call.
        """
        import time as _time

        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not configured")

        payload = self._build_payload(messages, temperature, max_tokens, stream=True)
        model = payload.get("model", "?")

        logger.info(
            f"[OPENROUTER-STREAM] connecting — model={model}, "
            f"messages={len(messages)}, max_tokens={max_tokens}"
        )
        _http_start = _time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{self.api_base}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    _connect_ms = (_time.monotonic() - _http_start) * 1000
                    logger.info(
                        f"[OPENROUTER-STREAM] HTTP {response.status_code} "
                        f"after {_connect_ms:.0f}ms"
                    )
                    response.raise_for_status()

                    _chunk_count = 0
                    _first_chunk_logged = False

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue

                        data = line.removeprefix("data: ").strip()
                        if data == "[DONE]":
                            logger.info(
                                f"[OPENROUTER-STREAM] [DONE] — "
                                f"chunks={_chunk_count}, "
                                f"elapsed={(_time.monotonic() - _http_start) * 1000:.0f}ms"
                            )
                            break

                        try:
                            _chunk_count += 1
                            if not _first_chunk_logged:
                                _first_ms = (_time.monotonic() - _http_start) * 1000
                                logger.info(
                                    f"[OPENROUTER-STREAM] first chunk after "
                                    f"{_first_ms:.0f}ms"
                                )
                                _first_chunk_logged = True
                            yield json.loads(data)
                        except json.JSONDecodeError:
                            logger.warning(
                                f"[OPENROUTER-STREAM] parse error: {data[:200]}"
                            )

        except httpx.TimeoutException:
            _elapsed = (_time.monotonic() - _http_start) * 1000
            logger.error(
                f"[OPENROUTER-STREAM] TIMEOUT after {_elapsed:.0f}ms "
                f"(limit={DEFAULT_TIMEOUT}s) — model={model}"
            )
            raise
        except httpx.HTTPStatusError as e:
            _elapsed = (_time.monotonic() - _http_start) * 1000
            _body = ""
            try:
                _body = e.response.text[:500]
            except Exception:
                pass
            logger.error(
                f"[OPENROUTER-STREAM] HTTP {e.response.status_code} after "
                f"{_elapsed:.0f}ms — body={_body}"
            )
            raise
        except Exception as e:
            _elapsed = (_time.monotonic() - _http_start) * 1000
            logger.error(
                f"[OPENROUTER-STREAM] ERROR {type(e).__name__}: {e} "
                f"after {_elapsed:.0f}ms"
            )
            raise

    def get_text_response(self, response: Dict[str, Any]) -> str:
        """
        Get assistant text content from OpenRouter response.
        """
        try:
            return response["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            return ""

    def get_usage(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract token usage from OpenRouter response.
        """
        usage = response.get("usage")
        return usage if isinstance(usage, dict) else {}

    async def aclose(self) -> None:
        """Close the reusable HTTP session."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


_client: Optional[OpenRouterClient] = None


def get_openrouter_client() -> OpenRouterClient:
    """Get or create OpenRouter client singleton."""
    global _client
    if _client is None:
        _client = OpenRouterClient()
    return _client
