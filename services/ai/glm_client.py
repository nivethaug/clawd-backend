"""
GLM API Client
Direct API calls to GLM-4.6 with tool support
"""

import os
import json
import logging
import httpx
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Configuration
Z_AI_API_KEY = os.getenv("Z_AI_API_KEY", "")
Z_AI_API_BASE = os.getenv("Z_AI_API_BASE", "https://api.z.ai/api/coding/paas/v4")
Z_AI_MODEL = os.getenv("Z_AI_MODEL", "GLM-4.5-Air")  # Can use GLM-4.6 if available
DEFAULT_TIMEOUT = 30.0
RETRY_TIMEOUT = 60.0


class GLMClient:
    """
    Direct GLM API client with tool calling support.
    
    Uses api.z.ai endpoint with Bearer token authentication.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize GLM client.
        
        Args:
            api_key: GLM API key (defaults to Z_AI_API_KEY env var)
            model: Model name (defaults to Z_AI_MODEL env var or GLM-4.5-Air)
        """
        self.api_key = api_key or Z_AI_API_KEY
        self.model = model or Z_AI_MODEL
        self.api_base = Z_AI_API_BASE
        
        if not self.api_key:
            logger.warning("[GLM-CLIENT] Z_AI_API_KEY not configured - API calls will fail")
    
    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
        temperature: float = 0.1,
        max_tokens: int = 1000
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
        logger.debug(f"[GLM-CLIENT] Calling GLM API with {len(messages)} messages, {tool_count} tools")
        
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "tools": tools,
                        "tool_choice": tool_choice,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    }
                )
                response.raise_for_status()
                data = response.json()
                
                logger.debug(f"[GLM-CLIENT] Response received (tokens: {data.get('usage', {})})")
                logger.info(f"[GLM-CLIENT] Response has tool_calls: {bool(data.get('choices', [{}])[0].get('message', {}).get('tool_calls'))}")
                logger.debug(f"[GLM-CLIENT] Full response: {json.dumps(data, indent=2)}")
                return data
                
            except httpx.TimeoutException:
                logger.warning(f"[GLM-CLIENT] Timeout after {DEFAULT_TIMEOUT}s, retrying with {RETRY_TIMEOUT}s")
                
                # Retry with longer timeout
                async with httpx.AsyncClient(timeout=RETRY_TIMEOUT) as retry_client:
                    response = await retry_client.post(
                        f"{self.api_base}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": self.model,
                            "messages": messages,
                            "tools": tools,
                            "tool_choice": tool_choice,
                            "temperature": temperature,
                            "max_tokens": max_tokens
                        }
                    )
                    response.raise_for_status()
                    data = response.json()
                    logger.info(f"[GLM-CLIENT] Retry successful")
                    return data
                    
            except httpx.HTTPStatusError as e:
                logger.error(f"[GLM-CLIENT] HTTP error {e.response.status_code}: {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"[GLM-CLIENT] Unexpected error: {e}")
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
                    "arguments": func.get("arguments")  # JSON string
                })
            
            logger.info(f"[GLM-CLIENT] Parsed {len(parsed)} tool calls")
            return parsed
            
        except (KeyError, IndexError) as e:
            logger.warning(f"[GLM-CLIENT] Failed to parse tool calls: {e}")
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


# Singleton instance
_client: Optional[GLMClient] = None


def get_glm_client() -> GLMClient:
    """Get or create GLM client singleton."""
    global _client
    if _client is None:
        _client = GLMClient()
    return _client
