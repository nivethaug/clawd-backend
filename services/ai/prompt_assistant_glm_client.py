"""
Prompt Assistant GLM API Client

Dedicated copy of the GLM client for DreamAgent Prompt Assistant completions.
Keeps the shared GLM client untouched while preserving the same request shape,
timeout, retry, logging, and response parsing conventions.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Configuration mirrors the shared GLM client, with a Prompt Assistant-specific
# model override so this chat can default to GLM-4.7-FlashX independently.
Z_AI_API_KEY = os.getenv("Z_AI_API_KEY", "")
Z_AI_API_BASE = os.getenv("Z_AI_API_BASE", "https://api.z.ai/api/coding/paas/v4")
PROMPT_ASSISTANT_GLM_MODEL = os.getenv("PROMPT_ASSISTANT_GLM_MODEL", "GLM-4.7-FlashX")
DEFAULT_TIMEOUT = 30.0
RETRY_TIMEOUT = 60.0


class PromptAssistantGLMClient:
    """
    Direct GLM API client for Prompt Assistant completions.

    Uses api.z.ai endpoint with Bearer token authentication.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize Prompt Assistant GLM client.

        Args:
            api_key: GLM API key (defaults to Z_AI_API_KEY env var)
            model: Model name (defaults to PROMPT_ASSISTANT_GLM_MODEL env var or GLM-4.7-FlashX)
        """
        self.api_key = api_key or Z_AI_API_KEY
        self.model = model or PROMPT_ASSISTANT_GLM_MODEL
        self.api_base = Z_AI_API_BASE

        if not self.api_key:
            logger.warning("[PROMPT-GLM-CLIENT] Z_AI_API_KEY not configured - API calls will fail")

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
        temperature: float = 0.1,
        max_tokens: int = 1000,
    ) -> Dict[str, Any]:
        """
        Call GLM API with tool support.

        Args:
            messages: Conversation messages (system, user, assistant)
            tools: Tool definitions (JSON Schema format)
            tool_choice: "auto" or "none" or specific tool
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response

        Returns:
            API response with potential tool_calls

        Raises:
            ValueError: If API key not configured
            httpx.HTTPError: If API call fails
        """
        if not self.api_key:
            raise ValueError("Z_AI_API_KEY not configured")

        tool_count = len(tools) if tools else 0
        logger.debug(f"[PROMPT-GLM-CLIENT] Calling GLM API with {len(messages)} messages, {tool_count} tools")

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "tools": tools,
                        "tool_choice": tool_choice,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "thinking": {"type": "disabled"},
                    },
                )
                response.raise_for_status()
                data = response.json()

                logger.debug(f"[PROMPT-GLM-CLIENT] Response received (tokens: {data.get('usage', {})})")
                logger.info(
                    "[PROMPT-GLM-CLIENT] Response has tool_calls: "
                    f"{bool(data.get('choices', [{}])[0].get('message', {}).get('tool_calls'))}"
                )
                logger.debug(f"[PROMPT-GLM-CLIENT] Full response: {json.dumps(data, indent=2)}")
                return data

            except httpx.TimeoutException:
                logger.warning(f"[PROMPT-GLM-CLIENT] Timeout after {DEFAULT_TIMEOUT}s, retrying with {RETRY_TIMEOUT}s")

                # Retry with longer timeout
                async with httpx.AsyncClient(timeout=RETRY_TIMEOUT) as retry_client:
                    response = await retry_client.post(
                        f"{self.api_base}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "messages": messages,
                            "tools": tools,
                            "tool_choice": tool_choice,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "thinking": {"type": "disabled"},
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    logger.info("[PROMPT-GLM-CLIENT] Retry successful")
                    return data

            except httpx.HTTPStatusError as e:
                logger.error(f"[PROMPT-GLM-CLIENT] HTTP error {e.response.status_code}: {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"[PROMPT-GLM-CLIENT] Unexpected error: {e}")
                raise

    def parse_tool_calls(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse tool calls from GLM response.

        Args:
            response: GLM API response

        Returns:
            List of tool calls: [{"name": str, "arguments": dict}]
        """
        try:
            message = response["choices"][0]["message"]
            tool_calls = message.get("tool_calls", [])

            parsed = []
            for tc in tool_calls:
                func = tc.get("function", {})
                parsed.append({
                    "id": tc.get("id"),
                    "name": func.get("name"),
                    "arguments": func.get("arguments"),
                })

            logger.info(f"[PROMPT-GLM-CLIENT] Parsed {len(parsed)} tool calls")
            return parsed

        except (KeyError, IndexError) as e:
            logger.warning(f"[PROMPT-GLM-CLIENT] Failed to parse tool calls: {e}")
            return []

    def get_text_response(self, response: Dict[str, Any]) -> str:
        """
        Get text content from GLM response (when no tool calls).

        Args:
            response: GLM API response

        Returns:
            Text content or empty string
        """
        try:
            return response["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            return ""


_client: Optional[PromptAssistantGLMClient] = None


def get_prompt_assistant_glm_client() -> PromptAssistantGLMClient:
    """Get or create Prompt Assistant GLM client singleton."""
    global _client
    if _client is None:
        _client = PromptAssistantGLMClient()
    return _client
